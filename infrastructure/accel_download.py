"""fetch the graphics engine, check it, and only then switch it on.

The libraries themselves come from a release asset built by
`.github/workflows/build-accel.yml` -- llama.cpp compiled with its Vulkan
backend, which nobody publishes so we build it ourselves.

Three things this is careful about, each for a reason:

**The size is read, not guessed.** A manifest beside the asset carries the
measured byte count, so the figure shown before asking for consent is the figure
that will actually be downloaded. An estimate is a promise broken at download
time.

**The checksum is verified.** A truncated download produces libraries that fail
to load in a way that looks exactly like an incompatible driver, and the user
would be told the wrong thing about their own machine.

**Nothing is switched on until a separate process has loaded it.** Extraction
finishing is not evidence the libraries work; see acceleration.activate.

Progress is shaped like `ModelDownloader`'s deliberately -- the UI already knows
how to poll and render that, and a second progress vocabulary would be a second
thing to keep in step.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tarfile
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from infrastructure import acceleration

logger = logging.getLogger(__name__)

# The rolling release the build workflow publishes to. A stable address, like
# the beta channel, so the app never has to discover a version.
ASSET_BASE = (
    "https://github.com/get-thinkstack/ThinkStack/releases/download/accel-latest"
)

CHUNK = 1024 * 256
NETWORK_TIMEOUT = 60


@dataclass
class AccelProgress:
    """live state of the engine download, polled by Bench."""
    status: str = "idle"   # idle | downloading | verifying | installing | done | error | cancelled
    total_bytes: int = 0
    downloaded_bytes: int = 0
    detail: str = ""
    error: str = ""

    @property
    def percent(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return round(self.downloaded_bytes / self.total_bytes * 100, 1)

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "percent": self.percent,
            "downloaded_mb": round(self.downloaded_bytes / 1048576, 1),
            "total_mb": round(self.total_bytes / 1048576, 1),
            "detail": self.detail,
            "error": self.error,
        }


def asset_names(platform_key: str) -> tuple[str, str]:
    stem = f"thinkstack-accel-vulkan-{platform_key}"
    return f"{stem}.tar.gz", f"{stem}.json"


def fetch_manifest(platform_key: str, *, opener=urllib.request.urlopen) -> dict | None:
    """the measured size and checksum, or None if it cannot be read.

    None means "do not offer a download", not "download blindly": without a
    manifest there is no honest number to show and nothing to verify against.
    """
    _, manifest_name = asset_names(platform_key)
    try:
        with opener(f"{ASSET_BASE}/{manifest_name}", timeout=NETWORK_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 - offline is a normal state here
        logger.info("no acceleration manifest available: %s", e)
        return None


class AccelInstaller:
    """runs one engine download at a time and reports progress."""

    def __init__(self) -> None:
        self._progress: AccelProgress | None = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    def progress(self) -> dict | None:
        p = self._progress
        return p.as_dict() if p else None

    def busy(self) -> bool:
        return bool(self._progress and self._progress.status in
                    ("downloading", "verifying", "installing"))

    def cancel(self) -> bool:
        if not self.busy():
            return False
        self._cancel.set()
        return True

    def install(self, data_dir: Path, platform_key: str,
                *, opener=urllib.request.urlopen) -> dict:
        """download, verify, extract, probe, activate. Never raises.

        Returns the final progress. The app is fully usable throughout: nothing
        touches the running engine until `activate` succeeds, and a failure at
        any step leaves the processor path exactly as it was.
        """
        with self._lock:
            if self.busy():
                return self._progress.as_dict()
            self._cancel.clear()
            prog = self._progress = AccelProgress(status="downloading")

        archive_name, _ = asset_names(platform_key)
        target = acceleration.accel_dir(data_dir) / f"vulkan-{platform_key}"
        staging = target.with_suffix(".partial")

        try:
            manifest = fetch_manifest(platform_key, opener=opener)
            if not manifest:
                raise RuntimeError(
                    "The graphics engine is not published for this platform yet."
                )
            prog.total_bytes = int(manifest.get("bytes") or 0)

            # ── download to a temporary file ──
            staging.parent.mkdir(parents=True, exist_ok=True)
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True)
            blob = staging / archive_name

            digest = hashlib.sha256()
            with opener(f"{ASSET_BASE}/{archive_name}", timeout=NETWORK_TIMEOUT) as r:
                if not prog.total_bytes:
                    prog.total_bytes = int(r.headers.get("content-length") or 0)
                with blob.open("wb") as fh:
                    while True:
                        if self._cancel.is_set():
                            prog.status = "cancelled"
                            shutil.rmtree(staging, ignore_errors=True)
                            return prog.as_dict()
                        chunk = r.read(CHUNK)
                        if not chunk:
                            break
                        fh.write(chunk)
                        digest.update(chunk)
                        prog.downloaded_bytes += len(chunk)

            # ── verify before trusting it ──
            prog.status = "verifying"
            expected = (manifest.get("sha256") or "").lower()
            if expected and digest.hexdigest() != expected:
                # a truncated download fails to load in a way indistinguishable
                # from an incompatible driver, and the user would be told
                # something untrue about their own machine
                raise RuntimeError(
                    "The download did not arrive intact. Nothing was changed; "
                    "try again."
                )

            # ── extract ──
            prog.status = "installing"
            prog.detail = "Unpacking"
            _extract(blob, staging)
            blob.unlink(missing_ok=True)

            lib = staging / "lib"
            if not lib.is_dir():
                raise RuntimeError("The downloaded engine is not shaped as expected.")

            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            staging.rename(target)

            # ── only now, and only if a separate process survives it ──
            prog.detail = "Checking it works on this machine"
            ok, detail = acceleration.activate(data_dir, target / "lib")
            if not ok:
                prog.status = "error"
                prog.error = (
                    f"The graphics engine downloaded but could not run here: "
                    f"{detail} ThinkStack is still using your processor."
                )
                return prog.as_dict()

            prog.status = "done"
            prog.detail = "Graphics acceleration is on. Restart to use it."
            return prog.as_dict()

        except Exception as e:  # noqa: BLE001 - reported, never raised at the UI
            logger.error("acceleration install failed: %s", e)
            shutil.rmtree(staging, ignore_errors=True)
            prog.status = "error"
            prog.error = str(e)
            return prog.as_dict()


def _extract(archive: Path, into: Path) -> None:
    """unpack, refusing any member that would escape the target directory.

    A tar member may name `../../etc/passwd`. This asset is ours and served over
    HTTPS, so the realistic risk is low -- but "the archive was trustworthy" is
    an assumption that costs nothing to remove, and the same check protects
    against a malformed build as much as a malicious one.
    """
    into = into.resolve()

    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.namelist():
                dest = (into / member).resolve()
                if dest != into and not dest.is_relative_to(into):
                    raise RuntimeError("The archive contains an unsafe path.")
            zf.extractall(into)
        return

    with tarfile.open(archive, "r:gz") as tf:
        for member in tf.getmembers():
            dest = (into / member.name).resolve()
            if dest != into and not dest.is_relative_to(into):
                raise RuntimeError("The archive contains an unsafe path.")
            if member.issym() or member.islnk():
                # a link inside the archive can point anywhere once extracted
                raise RuntimeError("The archive contains a link, which is not expected.")
        tf.extractall(into)


installer = AccelInstaller()
