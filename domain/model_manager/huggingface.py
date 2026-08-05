"""find GGUF models on Hugging Face.

The ONE part of ThinkStack that reaches the internet on purpose. Everything
else works offline and stays offline; this exists because a user who wants a
model we do not ship should not have to go and find the file themselves.

Three rules hold the offline-first promise while this exists:

  1. **Nothing here runs unless the user asked.** No prefetch, no background
     index, no "popular models" on page load. Every function below is the
     direct result of a click.
  2. **The UI says so.** A search box that quietly queries a remote API is
     exactly the behaviour this app claims not to have.
  3. **We build the download URL, never accept one.** The caller passes a repo
     id and a filename; the host is ours to decide. Accepting a URL would turn
     the model downloader into a general-purpose fetcher pointed by whoever can
     reach the local API.

The HTTP client is injected so the tests never touch the network. A test suite
that needs Hugging Face to be up is a test suite that fails on a train.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote

logger = logging.getLogger(__name__)

HF_API = "https://huggingface.co/api"
HF_HOST = "https://huggingface.co"

# Short: this runs while a user waits with a search box open. Hugging Face is
# usually fast, and an app that appears hung is worse than one that says it
# could not reach the network.
TIMEOUT_S = 8.0

# Quantisations worth offering, best trade-off first. GGUF repos frequently
# carry a dozen variants and most of the difference is irrelevant here: q4_k_m
# is the size/quality sweet spot for CPU inference, and anything below q3 is
# usually worse than a smaller model at the same size.
PREFERRED_QUANTS = ("q4_k_m", "q4_k_s", "q5_k_m", "q5_k_s", "q6_k", "q8_0", "q4_0", "q3_k_m")


class HttpClient(Protocol):
    """the slice of httpx this module uses, so a fake can stand in."""

    def get(self, url: str, **kwargs: Any) -> Any: ...


@dataclass(frozen=True)
class RepoSummary:
    """one Hugging Face repository, as a search result."""

    repo_id: str
    downloads: int = 0
    likes: int = 0
    updated: str = ""

    @property
    def owner(self) -> str:
        return self.repo_id.split("/")[0] if "/" in self.repo_id else ""

    @property
    def name(self) -> str:
        return self.repo_id.split("/")[-1]

    def as_dict(self) -> dict:
        return {
            "repo_id": self.repo_id,
            "owner": self.owner,
            "name": self.name,
            "downloads": self.downloads,
            "likes": self.likes,
            "updated": self.updated,
        }


@dataclass(frozen=True)
class RepoFile:
    """one downloadable .gguf inside a repository."""

    repo_id: str
    filename: str
    size_gb: float = 0.0

    @property
    def quant(self) -> str:
        """the quantisation label, e.g. "Q4_K_M", or "" when not recognisable."""
        stem = self.filename[:-5] if self.filename.lower().endswith(".gguf") else self.filename
        for part in reversed(stem.replace(".", "-").split("-")):
            if part.lower() in PREFERRED_QUANTS or (
                part and part[0].lower() in "qi" and any(c.isdigit() for c in part)
            ):
                return part.upper()
        return ""

    @property
    def url(self) -> str:
        """the download URL. Built here; never supplied by a caller."""
        return f"{HF_HOST}/{self.repo_id}/resolve/main/{quote(self.filename)}"

    def as_dict(self) -> dict:
        return {
            "repo_id": self.repo_id,
            "filename": self.filename,
            "size_gb": self.size_gb,
            "quant": self.quant,
            "url": self.url,
        }


class HuggingFaceError(RuntimeError):
    """a search or lookup failed. message is user-facing."""


def _default_client() -> HttpClient:
    import httpx

    return httpx  # module-level get() has the same shape we need


def _get_json(client: HttpClient, url: str, params: dict | None = None) -> Any:
    """GET json, turning every transport failure into one readable sentence.

    The caller is a UI, so an httpx exception repr is not an acceptable
    outcome. Each branch names something the user can act on: their connection,
    the repo id they typed, or "try again".
    """
    try:
        resp = client.get(url, params=params or {}, timeout=TIMEOUT_S,
                          follow_redirects=True)
    except Exception as e:  # noqa: BLE001 - httpx raises a wide family here
        logger.warning("hugging face request failed: %s", e)
        raise HuggingFaceError(
            "Could not reach Hugging Face. Check your internet connection — "
            "everything else in ThinkStack keeps working offline."
        ) from e

    status = getattr(resp, "status_code", 200)
    if status == 404:
        raise HuggingFaceError("No such model repository on Hugging Face.")
    if status == 401 or status == 403:
        raise HuggingFaceError(
            "That repository is private or gated, so ThinkStack cannot read it."
        )
    if status >= 400:
        raise HuggingFaceError(f"Hugging Face returned an error ({status}). Try again.")

    try:
        return resp.json()
    except Exception as e:  # noqa: BLE001
        raise HuggingFaceError("Hugging Face returned something unreadable.") from e


def search_gguf_models(
    query: str, limit: int = 20, client: HttpClient | None = None
) -> list[RepoSummary]:
    """repositories matching ``query`` that actually contain GGUF weights.

    Filtered to the ``gguf`` library tag rather than searching all of Hugging
    Face: ThinkStack loads GGUF and nothing else, so a result it cannot use is
    not a result. Sorted by downloads, which is a crude but honest proxy for
    "this one works" in a space full of broken conversions.
    """
    query = (query or "").strip()
    if not query:
        return []

    data = _get_json(
        client or _default_client(),
        f"{HF_API}/models",
        {
            "search": query,
            "filter": "gguf",
            "sort": "downloads",
            "direction": -1,
            "limit": max(1, min(limit, 50)),
        },
    )
    if not isinstance(data, list):
        return []

    out: list[RepoSummary] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        repo_id = str(item.get("modelId") or item.get("id") or "").strip()
        if not repo_id:
            continue
        out.append(RepoSummary(
            repo_id=repo_id,
            downloads=int(item.get("downloads") or 0),
            likes=int(item.get("likes") or 0),
            updated=str(item.get("lastModified") or ""),
        ))
    return out


def list_gguf_files(repo_id: str, client: HttpClient | None = None) -> list[RepoFile]:
    """every .gguf in ``repo_id``, smallest first.

    Sizes come from the tree endpoint, which reports them for LFS files. A repo
    that does not report one yields 0.0 rather than being dropped -- the user
    can still download it, they just do not get a fit-vs-memory check first.

    Multi-part GGUFs (``-00001-of-00003.gguf``) are excluded: llama.cpp needs
    every shard and the downloader fetches one file, so offering a part means
    offering a download that cannot load.
    """
    repo_id = (repo_id or "").strip().strip("/")
    if not repo_id or repo_id.count("/") != 1:
        raise HuggingFaceError(
            "A repository id looks like \"owner/name\", for example "
            "\"Qwen/Qwen2.5-1.5B-Instruct-GGUF\"."
        )

    data = _get_json(client or _default_client(), f"{HF_API}/models/{repo_id}/tree/main")
    if not isinstance(data, list):
        raise HuggingFaceError("That repository listed no files.")

    out: list[RepoFile] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if not path.lower().endswith(".gguf"):
            continue
        if _is_split_part(path):
            continue
        size = item.get("size") or (item.get("lfs") or {}).get("size") or 0
        out.append(RepoFile(
            repo_id=repo_id,
            filename=path,
            size_gb=round(int(size) / (1024 ** 3), 2) if size else 0.0,
        ))

    if not out:
        raise HuggingFaceError(
            "That repository has no single-file GGUF weights ThinkStack can use."
        )
    return sorted(out, key=lambda f: (f.size_gb or 999, f.filename))


def _is_split_part(filename: str) -> bool:
    """whether this is one shard of a multi-part GGUF."""
    low = filename.lower()
    return "-of-" in low and low.endswith(".gguf")


def build_download_url(repo_id: str, filename: str) -> str:
    """the URL for one file, constructed rather than accepted.

    This is the security boundary. A caller supplies a repo id and a filename;
    the scheme and host are fixed here. If the API accepted a URL instead, the
    model downloader would fetch anything anyone able to reach the local API
    asked it to -- and the local API is reachable from the webview, which runs
    remote-ish content.
    """
    repo_id = (repo_id or "").strip().strip("/")
    if repo_id.count("/") != 1 or not filename.lower().endswith(".gguf"):
        raise HuggingFaceError("That is not a downloadable GGUF file.")
    if ".." in repo_id or ".." in filename or filename.startswith("/"):
        raise HuggingFaceError("That file path is not valid.")
    return f"{HF_HOST}/{repo_id}/resolve/main/{quote(filename)}"


def pick_best_quant(files: list[RepoFile], budget_gb: float = 0.0) -> RepoFile | None:
    """the file to preselect: the best quantisation that fits.

    Saves the user reading eight variants to learn that six of them are the
    same model. They can still choose any of them; this only decides what is
    highlighted.
    """
    if not files:
        return None
    affordable = [f for f in files if budget_gb <= 0 or f.size_gb <= budget_gb] or files

    def rank(f: RepoFile) -> tuple[int, float]:
        q = f.quant.lower()
        try:
            return (PREFERRED_QUANTS.index(q), f.size_gb)
        except ValueError:
            return (len(PREFERRED_QUANTS), f.size_gb)

    return min(affordable, key=rank)


# convenience for callers that want one call instead of two
def lookup(
    repo_id: str, budget_gb: float = 0.0, client: HttpClient | None = None
) -> dict:
    """files in ``repo_id`` plus which one we would pick."""
    files = list_gguf_files(repo_id, client)
    best = pick_best_quant(files, budget_gb)
    return {
        "repo_id": repo_id,
        "files": [f.as_dict() for f in files],
        "recommended": best.filename if best else "",
    }
