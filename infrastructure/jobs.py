"""background analysis queue.

the local model is slow and there is exactly one of it. a gap scan measured
133 s and a per-paper summary+claims pass 50 s on this machine, so any route
that awaits one of those in the request handler is a route that appears to
hang. worse, the work was being paid for at the moment the user wanted to
*look* at something, which is the one moment it must not be.

so analysis moves off the request path entirely: uploading a paper enqueues
its analysis, and finishing that enqueues the library-wide re-cluster. by the
time the user opens LitGraph the summaries, claims and theme hulls are already
there.

deliberately not a job framework. there is one worker, one process, and a
handful of jobs; ``asyncio.Queue`` plus a task is the whole implementation, and
celery/rq/arq would each add a broker to run three functions in order.
durability is not needed either -- every job is derived from state already on
disk, so a job lost to a crash is recomputed on the next upload rather than
mattering.

ponytail: in-memory queue, single worker. a persistent queue only earns its
keep if a lost job means lost user data, and here it never does.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """one unit of queued work."""
    kind: str                       # "analyze" | "themes" | "gaps"
    label: str                      # human text for the progress strip
    run: Callable[[], Awaitable]    # the coroutine factory to await
    # jobs of a coalescing kind collapse: uploading five papers must trigger
    # one re-cluster, not five. set for library-wide work, clear for per-paper.
    coalesce: bool = False
    queued_at: float = field(default_factory=time.time)


class JobQueue:
    """single-worker async queue with a status view for the ui."""

    def __init__(self) -> None:
        self._q: "asyncio.Queue[Job]" = asyncio.Queue()
        self._worker: Optional[asyncio.Task] = None
        self._current: Optional[Job] = None
        self._pending_kinds: set[str] = set()
        # done/total describe the CURRENT run of work, not all time: the bar
        # resets when the queue drains, so "2 of 5" always means this batch.
        self._done = 0
        self._total = 0
        self._last_error: Optional[str] = None

    # ---- lifecycle ----

    def start(self) -> None:
        """spawn the worker. idempotent; safe to call from lifespan startup."""
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._loop())
            logger.info("job queue worker started")

    async def stop(self) -> None:
        """cancel the worker on shutdown."""
        if self._worker and not self._worker.done():
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        self._worker = None

    # ---- producing ----

    def submit(self, job: Job) -> bool:
        """queue a job. returns False when it was coalesced away.

        a coalescing job whose kind is already waiting is dropped: the queued
        one has not run yet, so it will pick up this change too.
        """
        if job.coalesce and job.kind in self._pending_kinds:
            logger.info("coalesced %s job -- one is already queued", job.kind)
            return False

        if job.coalesce:
            self._pending_kinds.add(job.kind)
        self._q.put_nowait(job)
        self._total += 1
        self.start()
        return True

    # ---- consuming ----

    async def _loop(self) -> None:
        while True:
            job = await self._q.get()
            self._current = job
            self._pending_kinds.discard(job.kind)
            started = time.time()
            try:
                await job.run()
                logger.info("job %s done in %.1fs", job.kind, time.time() - started)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - one bad job must not kill the worker
                self._last_error = f"{job.kind}: {e}"
                logger.error("job %s failed: %s", job.kind, e, exc_info=True)
            finally:
                self._done += 1
                self._current = None
                self._q.task_done()
                # queue drained -- reset the counters so the next batch counts
                # from one rather than continuing to climb forever.
                if self._q.empty():
                    self._done = 0
                    self._total = 0

    # ---- status ----

    def status(self) -> dict:
        """what the progress strip needs, in one call.

        ``total`` is the size of the current batch and ``done`` how many of it
        have finished, so the client can render a determinate bar. both are 0
        when nothing is running, which is the client's cue to render nothing.
        """
        return {
            "running": self._current.kind if self._current else None,
            "label": self._current.label if self._current else "",
            "queued": self._q.qsize(),
            "done": self._done,
            "total": self._total,
            "last_error": self._last_error,
        }


# app-wide singleton. created eagerly, started from the FastAPI lifespan so the
# worker binds to the running loop rather than whichever one imported this.
job_queue = JobQueue()
