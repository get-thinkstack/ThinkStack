"""Analysis: summaries, claims and themes, over the local model.

`document_analysis` (summary + claims in one call) is the per-paper unit that
`precompute` queues after each ingest and writes to the analysis cache, which
the canvas and the gap finder read. `parsing` coerces small-model JSON into
the shapes the callers expect.
"""
