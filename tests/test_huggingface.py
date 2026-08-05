"""searching Hugging Face for GGUF models, with no network.

Every test injects a fake client. A suite that needs huggingface.co to be up is
a suite that fails on a train, in CI behind a proxy, and on the offline machine
this app is built for -- and the whole point of this module is that reaching the
internet is a deliberate, isolated act.

The security-shaped tests matter most: `build_download_url` is what stops the
model downloader becoming a general-purpose fetcher aimed by whoever can reach
the local API, and the webview can reach the local API.
"""

from __future__ import annotations

import pytest

from domain.model_manager.huggingface import (
    HF_HOST,
    HuggingFaceError,
    RepoFile,
    build_download_url,
    list_gguf_files,
    lookup,
    pick_best_quant,
    search_gguf_models,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeClient:
    """records what was asked for, answers with whatever it was given."""

    def __init__(self, payload=None, status_code=200, raises=None):
        self.payload = payload
        self.status_code = status_code
        self.raises = raises
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("params") or {}))
        if self.raises:
            raise self.raises
        return FakeResponse(self.payload, self.status_code)


SEARCH_PAYLOAD = [
    {"modelId": "Qwen/Qwen2.5-1.5B-Instruct-GGUF", "downloads": 90000, "likes": 120,
     "lastModified": "2026-01-02T00:00:00.000Z"},
    {"id": "unsloth/Llama-3.2-3B-Instruct-GGUF", "downloads": 4000, "likes": 30},
    {"no_id_at_all": True},
]

TREE_PAYLOAD = [
    {"path": "README.md", "size": 900},
    {"path": "qwen2.5-1.5b-instruct-q4_k_m.gguf", "size": 1_120_000_000},
    {"path": "qwen2.5-1.5b-instruct-q8_0.gguf", "size": 1_900_000_000},
    {"path": "qwen2.5-1.5b-instruct-q2_k.gguf", "lfs": {"size": 700_000_000}},
    {"path": "big-model-00001-of-00003.gguf", "size": 5_000_000_000},
]


class TestSearch:
    def test_returns_repositories(self):
        c = FakeClient(SEARCH_PAYLOAD)
        got = search_gguf_models("qwen", client=c)
        assert [r.repo_id for r in got] == [
            "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
            "unsloth/Llama-3.2-3B-Instruct-GGUF",
        ]

    def test_it_filters_to_gguf_repositories(self):
        # ThinkStack loads GGUF and nothing else, so a result it cannot use is
        # not a result.
        c = FakeClient(SEARCH_PAYLOAD)
        search_gguf_models("qwen", client=c)
        _, params = c.calls[0]
        assert params["filter"] == "gguf"

    def test_an_entry_without_an_id_is_skipped_not_fatal(self):
        assert len(search_gguf_models("qwen", client=FakeClient(SEARCH_PAYLOAD))) == 2

    def test_owner_and_name_are_split_out(self):
        got = search_gguf_models("qwen", client=FakeClient(SEARCH_PAYLOAD))[0]
        assert got.owner == "Qwen"
        assert got.name == "Qwen2.5-1.5B-Instruct-GGUF"

    def test_an_empty_query_never_reaches_the_network(self):
        c = FakeClient(SEARCH_PAYLOAD)
        assert search_gguf_models("   ", client=c) == []
        assert c.calls == [], "an empty box must not fire a request"

    def test_the_limit_is_clamped(self):
        c = FakeClient([])
        search_gguf_models("q", limit=9999, client=c)
        assert c.calls[0][1]["limit"] <= 50

    def test_a_non_list_response_degrades_to_empty(self):
        assert search_gguf_models("q", client=FakeClient({"unexpected": "shape"})) == []


class TestNetworkFailuresAreReadable:
    def test_no_connection_says_so_in_english(self):
        c = FakeClient(raises=OSError("nodename nor servname provided"))
        with pytest.raises(HuggingFaceError, match="Could not reach Hugging Face"):
            search_gguf_models("qwen", client=c)

    def test_a_404_names_the_repository(self):
        with pytest.raises(HuggingFaceError, match="No such model repository"):
            list_gguf_files("nobody/nothing", client=FakeClient([], status_code=404))

    def test_a_gated_repo_says_it_is_gated(self):
        with pytest.raises(HuggingFaceError, match="private or gated"):
            list_gguf_files("meta/secret", client=FakeClient([], status_code=403))

    def test_unparseable_json_is_not_a_traceback(self):
        c = FakeClient(ValueError("not json"))
        with pytest.raises(HuggingFaceError, match="unreadable"):
            search_gguf_models("q", client=c)

    def test_every_message_is_fit_to_show_a_user(self):
        for client in (FakeClient([], status_code=404),
                       FakeClient([], status_code=500),
                       FakeClient(raises=OSError("boom"))):
            try:
                list_gguf_files("a/b", client=client)
            except HuggingFaceError as e:
                assert str(e)[0].isupper()
                assert "Traceback" not in str(e)


class TestListingFiles:
    def test_only_gguf_files_are_returned(self):
        got = list_gguf_files("Qwen/X-GGUF", client=FakeClient(TREE_PAYLOAD))
        assert all(f.filename.endswith(".gguf") for f in got)
        assert not any(f.filename == "README.md" for f in got)

    def test_multi_part_models_are_excluded(self):
        # llama.cpp needs every shard and the downloader fetches one file, so
        # offering a part is offering a download that cannot load.
        got = list_gguf_files("Qwen/X-GGUF", client=FakeClient(TREE_PAYLOAD))
        assert not any("-of-" in f.filename for f in got)

    def test_sizes_come_from_either_size_or_lfs_size(self):
        got = {f.filename: f.size_gb for f in
               list_gguf_files("Qwen/X-GGUF", client=FakeClient(TREE_PAYLOAD))}
        assert got["qwen2.5-1.5b-instruct-q4_k_m.gguf"] == pytest.approx(1.04, abs=0.02)
        assert got["qwen2.5-1.5b-instruct-q2_k.gguf"] == pytest.approx(0.65, abs=0.02)

    def test_smallest_first(self):
        sizes = [f.size_gb for f in list_gguf_files("Q/X", client=FakeClient(TREE_PAYLOAD))]
        assert sizes == sorted(sizes)

    def test_a_repo_with_no_usable_gguf_says_so(self):
        c = FakeClient([{"path": "README.md", "size": 1}])
        with pytest.raises(HuggingFaceError, match="no single-file GGUF"):
            list_gguf_files("a/b", client=c)

    @pytest.mark.parametrize("bad", ["", "   ", "justaname", "too/many/slashes", "/"])
    def test_a_malformed_repo_id_is_rejected_before_any_request(self, bad):
        c = FakeClient(TREE_PAYLOAD)
        with pytest.raises(HuggingFaceError, match="owner/name"):
            list_gguf_files(bad, client=c)
        assert c.calls == [], "a bad id must not cost a network round trip"


class TestQuantDetection:
    @pytest.mark.parametrize("filename,expected", [
        ("qwen2.5-1.5b-instruct-q4_k_m.gguf", "Q4_K_M"),
        ("Llama-3.2-3B-Instruct-Q4_K_M.gguf", "Q4_K_M"),
        ("model.Q8_0.gguf", "Q8_0"),
        ("something-iq3_xs.gguf", "IQ3_XS"),
    ])
    def test_reads_the_quantisation(self, filename, expected):
        assert RepoFile("a/b", filename).quant == expected

    def test_an_unrecognisable_name_yields_no_quant_rather_than_nonsense(self):
        assert RepoFile("a/b", "model.gguf").quant == ""


class TestPickBestQuant:
    def test_prefers_q4_k_m(self):
        files = list_gguf_files("Q/X", client=FakeClient(TREE_PAYLOAD))
        assert pick_best_quant(files).filename.endswith("q4_k_m.gguf")

    def test_falls_back_to_something_that_fits(self):
        files = list_gguf_files("Q/X", client=FakeClient(TREE_PAYLOAD))
        best = pick_best_quant(files, budget_gb=0.8)
        assert best.size_gb <= 0.8

    def test_an_impossible_budget_still_returns_a_choice(self):
        # refusing to preselect anything just leaves the user with no default;
        # they can still read the sizes and decide.
        files = list_gguf_files("Q/X", client=FakeClient(TREE_PAYLOAD))
        assert pick_best_quant(files, budget_gb=0.001) is not None

    def test_no_files_means_no_pick(self):
        assert pick_best_quant([]) is None


class TestDownloadUrlIsConstructedNeverAccepted:
    """The security boundary. The local API is reachable from the webview."""

    def test_builds_a_huggingface_url(self):
        url = build_download_url("Qwen/X-GGUF", "model-q4_k_m.gguf")
        assert url == f"{HF_HOST}/Qwen/X-GGUF/resolve/main/model-q4_k_m.gguf"

    def test_always_points_at_huggingface(self):
        assert build_download_url("a/b", "m.gguf").startswith(HF_HOST + "/")

    @pytest.mark.parametrize("repo,filename", [
        ("../../etc", "passwd.gguf"),
        ("a/b", "../../../etc/passwd.gguf"),
        ("a/b", "/etc/passwd.gguf"),
        ("a/b", "model.exe"),
        ("evil.com/x", "m.bin"),
        ("nota-repo", "m.gguf"),
    ])
    def test_traversal_and_non_gguf_are_refused(self, repo, filename):
        with pytest.raises(HuggingFaceError):
            build_download_url(repo, filename)

    def test_spaces_are_encoded_not_passed_through(self):
        url = build_download_url("a/b", "my model.gguf")
        assert " " not in url and "%20" in url


class TestLookup:
    def test_returns_files_and_a_recommendation(self):
        got = lookup("Qwen/X-GGUF", budget_gb=4.0, client=FakeClient(TREE_PAYLOAD))
        assert got["repo_id"] == "Qwen/X-GGUF"
        assert len(got["files"]) == 3
        assert got["recommended"].endswith("q4_k_m.gguf")
        assert all(f["url"].startswith(HF_HOST) for f in got["files"])
