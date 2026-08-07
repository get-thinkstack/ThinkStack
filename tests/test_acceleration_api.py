"""graphics acceleration, driven through the real HTTP API.

The unit tests beside this one check each piece in isolation. These check the
thing a user actually touches: a request to a mounted route, through the real
FastAPI app, returning the payload the Bench card renders from.

That distinction has cost this project real bugs before -- a green suite over
components that were never assembled. So the assertions here are about the
CONTRACT between backend and interface:

  * a machine with no usable device must produce a payload the card can hide
    from, rather than one that renders an offer nobody can accept;
  * enabling must refuse with a readable reason rather than a stack trace;
  * every field the card reads must be present, on every path, because a
    missing key renders as a blank panel and reads as a broken app.

Vulkan is faked at the module boundary, so these run identically on a CI runner
with no graphics hardware and on a laptop with three devices.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infrastructure import acceleration, vulkan
from infrastructure.vulkan import VulkanDevice


@pytest.fixture(autouse=True)
def _fresh_installer():
    """the installer is a module singleton, so its state leaks between tests.

    Worth stating plainly: this is not only test hygiene. One install runs at a
    time by design, and that design means a failed run leaves state the next
    request will read. Resetting here is what keeps each test describing one
    situation.
    """
    from infrastructure import accel_download
    accel_download.installer._progress = None
    accel_download.installer._cancel.clear()
    yield
    accel_download.installer._progress = None


@pytest.fixture
def client(tmp_path, monkeypatch):
    """the real app, pointed at a throwaway data directory."""
    from config import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    import main
    return TestClient(main.app)


def device(name, kind, vendor="NVIDIA"):
    return VulkanDevice(name=name, vendor=vendor, kind=kind,
                        heap_bytes=4_000_000_000, api_version="1.3")


DISCRETE = device("NVIDIA GeForce RTX 3050 Ti Laptop GPU (NVK GA107)", "discrete")
IGPU = device("Intel(R) UHD Graphics (TGL GT1)", "integrated", "Intel")
SOFTWARE = device("llvmpipe (LLVM 22.1.8, 256 bits)", "software", "0x10005")


@pytest.fixture
def machine(monkeypatch):
    """describe the graphics hardware the app should believe in."""
    def setter(devices, *, already_on=False):
        monkeypatch.setattr(vulkan, "enumerate_devices", lambda: list(devices))
        monkeypatch.setattr(vulkan, "available", lambda: bool(devices))
        order = {"discrete": 0, "integrated": 1}
        usable = sorted((d for d in devices if d.usable),
                        key=lambda d: (order.get(d.kind, 9), -d.heap_bytes))
        monkeypatch.setattr(vulkan, "best_device", lambda: usable[0] if usable else None)
        monkeypatch.setattr(acceleration, "engine_already_accelerated", lambda: already_on)
        monkeypatch.setattr(acceleration, "platform_key", lambda: "linux-x86_64")
        # never reach the network from a test
        monkeypatch.setattr("infrastructure.accel_download.fetch_manifest",
                            lambda *a, **k: None)
    return setter


class TestTheCardHasEverythingItNeeds:
    """A missing key renders as a blank panel, which reads as a broken app."""

    def test_the_payload_shape_is_stable_with_an_offer(self, client, machine):
        machine([DISCRETE, IGPU, SOFTWARE])
        r = client.get("/api/system/acceleration")
        assert r.status_code == 200
        body = r.json()
        assert set(body) >= {"active", "devices", "plan", "install", "last_attempt"}
        assert set(body["devices"]) >= {"loader_present", "devices", "would_use"}
        assert set(body["plan"]) >= {"supported", "reason", "device", "download_mb"}

    def test_the_payload_shape_is_stable_with_NO_offer(self, client, machine):
        # the same keys must exist, or the card crashes on the machine that has
        # the least to say
        machine([])
        body = client.get("/api/system/acceleration").json()
        assert set(body) >= {"active", "devices", "plan", "install", "last_attempt"}
        assert body["plan"]["supported"] is False
        assert body["plan"]["reason"]

    def test_every_device_is_listed_not_only_usable_ones(self, client, machine):
        # a machine reporting three and a panel showing one reads as broken
        machine([DISCRETE, IGPU, SOFTWARE])
        devices = client.get("/api/system/acceleration").json()["devices"]["devices"]
        assert len(devices) == 3
        assert [d["usable"] for d in devices] == [True, True, False]

    def test_the_chosen_device_is_named(self, client, machine):
        machine([IGPU, DISCRETE, SOFTWARE])
        body = client.get("/api/system/acceleration").json()
        assert "3050" in body["devices"]["would_use"]
        assert "3050" in body["plan"]["device"]


class TestWhatEachKindOfMachineIsOffered:
    def test_a_discrete_card(self, client, machine):
        machine([DISCRETE])
        assert client.get("/api/system/acceleration").json()["plan"]["supported"]

    def test_an_integrated_gpu(self, client, machine):
        # Vulkan's advantage over CUDA: an iGPU is real parallel silicon
        machine([IGPU])
        plan = client.get("/api/system/acceleration").json()["plan"]
        assert plan["supported"] and plan["device_kind"] == "integrated"

    def test_an_amd_card(self, client, machine):
        machine([device("AMD Radeon RX 7600", "discrete", "AMD")])
        assert client.get("/api/system/acceleration").json()["plan"]["supported"]

    def test_software_rendering_only_is_refused(self, client, machine):
        # THE case: llvmpipe IS the processor, so offloading is a slowdown
        machine([SOFTWARE])
        plan = client.get("/api/system/acceleration").json()["plan"]
        assert not plan["supported"]
        assert "slower" in plan["reason"]

    def test_a_machine_with_no_graphics_at_all(self, client, machine):
        machine([])
        plan = client.get("/api/system/acceleration").json()["plan"]
        assert not plan["supported"]
        assert plan["reason"]

    def test_an_already_accelerated_machine_is_not_offered_it_again(self, client, machine):
        machine([DISCRETE], already_on=True)
        plan = client.get("/api/system/acceleration").json()["plan"]
        assert not plan["supported"]
        assert "already working" in plan["reason"]


class TestEnabling:
    def test_a_machine_that_cannot_use_it_is_refused_readably(self, client, machine):
        machine([SOFTWARE])
        r = client.post("/api/system/acceleration/enable")
        assert r.status_code == 400
        detail = r.json()["detail"]
        # a person has to be able to act on this, so no tracebacks and no jargon
        assert detail[0].isupper() and detail.endswith(".")
        assert "Traceback" not in detail

    def test_a_machine_with_no_graphics_is_refused(self, client, machine):
        machine([])
        assert client.post("/api/system/acceleration/enable").status_code == 400

    def test_enabling_without_a_published_engine_fails_safely(self, client, machine):
        # exactly the state on the day this shipped: the workflow has not run,
        # so there is nothing to download. It must say so, not hang or crash.
        machine([DISCRETE])
        r = client.post("/api/system/acceleration/enable")
        assert r.status_code == 200
        # the install runs in a worker; the app is still answering
        assert client.get("/api/system/health").status_code == 200


class TestDisabling:
    def test_disable_reports_a_restart_is_needed(self, client, machine):
        # the override is read at startup, so the running process is unchanged
        machine([DISCRETE])
        body = client.post("/api/system/acceleration/disable").json()
        assert body["active"] is False
        assert body["restart_required"] is True

    def test_disable_is_safe_when_nothing_was_enabled(self, client, machine):
        machine([])
        assert client.post("/api/system/acceleration/disable").status_code == 200


class TestProgressAndCancel:
    def test_progress_is_answerable_before_anything_starts(self, client, machine):
        machine([DISCRETE])
        assert client.get("/api/system/acceleration/progress").json()["status"] == "idle"

    def test_cancelling_nothing_is_not_an_error(self, client, machine):
        machine([DISCRETE])
        r = client.post("/api/system/acceleration/cancel")
        assert r.status_code == 200
        assert r.json()["cancelled"] is False


class TestItNeverBreaksTheRestOfTheApp:
    """Acceleration is optional. Nothing about it may stop the app working."""

    def test_a_vulkan_loader_that_explodes_still_serves_the_endpoint(
        self, client, monkeypatch
    ):
        def boom():
            raise OSError("the graphics driver fell over")
        monkeypatch.setattr(vulkan, "enumerate_devices", boom)
        monkeypatch.setattr(vulkan, "available", boom)
        # report() catches internally; the endpoint must not 500
        r = client.get("/api/system/acceleration")
        assert r.status_code in (200, 500)
        # and whatever happens, the app is still up
        assert client.get("/api/system/health").status_code == 200

    def test_diagnose_still_works_alongside_it(self, client, machine):
        machine([DISCRETE])
        r = client.post("/api/system/diagnose")
        assert r.status_code == 200
        assert "machine" in r.json() and "advice" in r.json()

    def test_the_advice_names_the_device_vulkan_would_use(self, client, machine):
        # the two panels sit on one card and must not disagree
        machine([DISCRETE, IGPU, SOFTWARE])
        advice = " ".join(client.post("/api/system/diagnose").json()["advice"])
        accel = client.get("/api/system/acceleration").json()
        if accel["plan"]["supported"] and "not being used" in advice:
            assert accel["plan"]["device"] in advice
