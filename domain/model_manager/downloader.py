"""download optional models, with progress and consent.

only ever called after the user explicitly agrees (the app is offline-first, so
it must not reach out to the network on its own). downloads stream to a .part
file and are renamed into place only on success, so an interrupted download can
never leave a truncated .gguf that llama.cpp would fail to load.
"""

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from domain.model_manager.catalog import ModelSpec

logger = logging.getLogger(__name__)

_CHUNK = 1024 * 1024  # 1 MiB


@dataclass
class DownloadProgress:
    """live state of one download, polled by the UI."""

    name: str
    total_bytes: int = 0
    downloaded_bytes: int = 0
    status: str = "idle"  # idle | downloading | done | error | cancelled
    error: str = ""

    @property
    def percent(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return round(self.downloaded_bytes / self.total_bytes * 100, 1)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status,
            "percent": self.percent,
            "downloaded_mb": round(self.downloaded_bytes / (1024 ** 2), 1),
            "total_mb": round(self.total_bytes / (1024 ** 2), 1),
            "error": self.error,
        }


class ModelDownloader:
    """runs one download at a time and reports progress.

    single-slot on purpose: concurrent multi-gigabyte downloads on a machine we
    already know is memory- and disk-constrained would just make both slower.
    """

    def __init__(self) -> None:
        self._progress: DownloadProgress | None = None
        self._cancel = threading.Event()
        self._lock = threading.Lock()

    @property
    def progress(self) -> dict | None:
        p = self._progress
        return p.as_dict() if p else None

    def is_active(self) -> bool:
        return self._progress is not None and self._progress.status == "downloading"

    def cancel(self) -> bool:
        """ask an in-flight download to stop. returns whether one was running."""
        if not self.is_active():
            return False
        self._cancel.set()
        return True

    def download(self, spec: ModelSpec, models_dir: Path) -> dict:
        """fetch ``spec`` into ``models_dir``. blocking; run it in a thread.

        returns the final progress dict. never raises for network problems --
        failures are reported through status/error so the UI can offer a retry
        and the app keeps working on the bundled baseline.
        """
        with self._lock:
            if self.is_active():
                return {"status": "error", "error": "another download is already running"}
            self._cancel.clear()
            self._progress = DownloadProgress(name=spec.name, status="downloading")

        prog = self._progress
        target = models_dir / spec.name
        part = models_dir / f"{spec.name}.part"

        try:
            models_dir.mkdir(parents=True, exist_ok=True)

            if target.is_file():
                prog.status = "done"
                logger.info("%s already present, nothing to download", spec.name)
                return prog.as_dict()

            import httpx

            # generous timeout: these are ~1 GB files on unknown connections, but
            # a stalled read must not hang forever.
            with httpx.stream(
                "GET", spec.url, follow_redirects=True, timeout=httpx.Timeout(30.0, read=60.0)
            ) as resp:
                resp.raise_for_status()
                prog.total_bytes = int(resp.headers.get("content-length") or 0)

                with open(part, "wb") as f:
                    for chunk in resp.iter_bytes(_CHUNK):
                        if self._cancel.is_set():
                            prog.status = "cancelled"
                            f.close()
                            part.unlink(missing_ok=True)
                            logger.info("download of %s cancelled by user", spec.name)
                            return prog.as_dict()
                        f.write(chunk)
                        prog.downloaded_bytes += len(chunk)

            # only now is the file complete -- atomic rename into place
            part.replace(target)
            prog.status = "done"
            logger.info(
                "downloaded %s (%.2f gb) to %s",
                spec.name, prog.downloaded_bytes / (1024 ** 3), target,
            )

        except Exception as e:  # noqa: BLE001 - surfaced via status, never fatal
            prog.status = "error"
            prog.error = str(e)
            part.unlink(missing_ok=True)
            logger.warning("download of %s failed: %s", spec.name, e)

        return prog.as_dict()


# module-level singleton; the api routes share this one instance
downloader = ModelDownloader()
