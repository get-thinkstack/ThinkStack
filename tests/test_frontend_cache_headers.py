"""The bundled UI must never be served stale after an update.

The desktop shell is a WebKit view pointed at http://127.0.0.1:8000, and its
HTTP cache outlives the application: updating the app replaces the binary, not
the cache. Nothing sent a cache header, so WebKit applied heuristic freshness
and could reuse index.html without revalidating.

index.html is the file that breaks, because its name never changes. A stale
copy keeps referencing the previous build's asset filenames, so an updated app
renders the old UI and reports the old __APP_VERSION__ -- which is precisely
what was reported after 1.6.8 shipped: a freshly downloaded build still showing
v1.6.7 and the old two-button Analysis screen.

Assets are content-hashed by Vite, so a new build is always a new URL and can
be cached permanently.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A real app instance serving a throwaway frontend/dist."""
    dist = tmp_path / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><script src="/assets/index-abc123.js"></script>'
    )
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)")
    (dist / "favicon.ico").write_bytes(b"\x00")

    import config

    monkeypatch.setattr(config.settings, "base_dir", tmp_path)

    import importlib

    import main

    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c
    importlib.reload(main)


def cache_of(response) -> str:
    return response.headers.get("cache-control", "").lower()


class TestIndexHtmlIsNeverCached:
    def test_root_is_no_store(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "no-store" in cache_of(r)

    def test_a_client_route_is_no_store(self, client):
        # /analysis falls back to index.html; it must not be cached either.
        r = client.get("/analysis")
        assert r.status_code == 200
        assert "no-store" in cache_of(r)

    def test_index_is_not_marked_immutable(self, client):
        # The specific mistake that caused the bug: treating index.html like
        # a hashed asset.
        assert "immutable" not in cache_of(client.get("/"))

    def test_a_stable_named_file_is_not_cached_forever(self, client):
        # favicon.ico keeps its name across builds, so it has the same hazard.
        r = client.get("/favicon.ico")
        assert r.status_code == 200
        assert "immutable" not in cache_of(r)


class TestHashedAssetsAreCachedForever:
    def test_mounted_asset_is_immutable(self, client):
        r = client.get("/assets/index-abc123.js")
        assert r.status_code == 200
        cc = cache_of(r)
        assert "immutable" in cc
        assert "max-age=31536000" in cc

    def test_a_missing_asset_does_not_fall_back_to_index(self, client):
        # Falling back would serve HTML as JavaScript, and cache it forever.
        r = client.get("/assets/does-not-exist.js")
        assert r.status_code == 404


class TestApiIsUntouched:
    def test_api_paths_still_404_rather_than_serving_the_spa(self, client):
        assert client.get("/api/definitely-not-a-route").status_code == 404

    def test_health_still_works(self, client):
        r = client.get("/api/system/health")
        assert r.status_code == 200
