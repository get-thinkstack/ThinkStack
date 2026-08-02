"""
litgraph api routes.

serves the spatial map of the library. the graph is derived on every request
from data that already persists -- embeddings, the analysis cache, and past
analysis and gap runs -- so there is nothing to invalidate and no new state
to keep consistent. no language-model call happens here.
"""

import logging

from fastapi import APIRouter

from domain.litgraph.graph_builder import build_graph

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def graph():
    """return the library graph: nodes, edges, themes and gaps.

    returns:
        the full graph payload. every collection is present even when empty
        so the client can show a per-layer empty state instead of guessing
        whether a layer is absent or merely switched off.
    """
    return build_graph()
