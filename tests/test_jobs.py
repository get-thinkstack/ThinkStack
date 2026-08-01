"""the background analysis queue.

what matters here is not that a coroutine runs -- it is that uploading five
papers re-clusters once, that a failing job does not take the worker down with
it, and that the progress counters describe the current batch rather than
climbing forever.
"""

import asyncio

import pytest

from infrastructure.jobs import Job, JobQueue


@pytest.fixture
def q():
    return JobQueue()


async def _drain(q: JobQueue, timeout: float = 2.0) -> None:
    """let the worker finish everything currently queued."""
    q.start()
    await asyncio.wait_for(q._q.join(), timeout=timeout)
    await q.stop()


@pytest.mark.asyncio
class TestCoalescing:
    async def test_five_uploads_trigger_one_recluster(self, q):
        # THE regression this exists for: a library-wide job must not run once
        # per uploaded paper.
        runs = []
        for _ in range(5):
            q.submit(Job("themes", "l", lambda: _record(runs, "themes"), coalesce=True))
        await _drain(q)
        assert runs == ["themes"]

    async def test_per_paper_jobs_do_not_coalesce(self, q):
        # each paper genuinely needs its own analysis
        runs = []
        for i in range(3):
            q.submit(Job("analyze", "l", lambda i=i: _record(runs, i)))
        await _drain(q)
        assert sorted(runs) == [0, 1, 2]

    async def test_a_coalesced_job_is_reported_as_not_queued(self, q):
        q.submit(Job("themes", "l", _noop, coalesce=True))
        assert q.submit(Job("themes", "l", _noop, coalesce=True)) is False

    async def test_the_kind_can_be_queued_again_once_it_has_run(self, q):
        runs = []
        q.submit(Job("themes", "l", lambda: _record(runs, 1), coalesce=True))
        await _drain(q)
        q.submit(Job("themes", "l", lambda: _record(runs, 2), coalesce=True))
        await _drain(q)
        assert runs == [1, 2]


@pytest.mark.asyncio
class TestOrdering:
    async def test_jobs_run_in_submission_order(self, q):
        # gaps read the summaries analyze writes, so order is correctness,
        # not cosmetics.
        runs = []
        q.submit(Job("analyze", "l", lambda: _record(runs, "analyze")))
        q.submit(Job("themes", "l", lambda: _record(runs, "themes"), coalesce=True))
        q.submit(Job("gaps", "l", lambda: _record(runs, "gaps"), coalesce=True))
        await _drain(q)
        assert runs == ["analyze", "themes", "gaps"]


@pytest.mark.asyncio
class TestFailureIsolation:
    async def test_one_failing_job_does_not_stop_the_others(self, q):
        runs = []
        q.submit(Job("analyze", "l", _boom))
        q.submit(Job("analyze", "l", lambda: _record(runs, "after")))
        await _drain(q)
        assert runs == ["after"]

    async def test_the_failure_is_reported_not_swallowed(self, q):
        q.submit(Job("analyze", "l", _boom))
        await _drain(q)
        assert "kaboom" in (q.status()["last_error"] or "")


@pytest.mark.asyncio
class TestStatus:
    async def test_idle_reports_zeroes_so_the_ui_draws_nothing(self, q):
        s = q.status()
        assert (s["running"], s["queued"], s["total"]) == (None, 0, 0)

    async def test_total_counts_the_current_batch(self, q):
        q.submit(Job("analyze", "l", _noop))
        q.submit(Job("analyze", "l", _noop))
        assert q.status()["total"] == 2

    async def test_counters_reset_once_the_queue_drains(self, q):
        # otherwise "done 7 of 7" persists into the next upload and the bar
        # starts full.
        q.submit(Job("analyze", "l", _noop))
        await _drain(q)
        s = q.status()
        assert (s["done"], s["total"]) == (0, 0)

    async def test_a_second_batch_counts_from_one_again(self, q):
        q.submit(Job("analyze", "l", _noop))
        await _drain(q)
        q.submit(Job("analyze", "l", _noop))
        assert q.status()["total"] == 1


async def _noop():
    return None


async def _boom():
    raise RuntimeError("kaboom")


async def _record(sink: list, value) -> None:
    sink.append(value)
