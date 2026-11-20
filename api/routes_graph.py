"""LitGraph route: the map of the library (domain/litgraph/graph_builder.py).

Rebuilt on every request from what already persists (embeddings, the analysis
cache, past runs), so there is no graph state to invalidate. No model call.
"""

import logging

from fastapi import APIRouter

from domain.litgraph.graph_builder import build_graph

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("")
async def graph():
    """Nodes, edges, themes and gaps.

    Every collection is present even when empty, so the client can tell an
    empty layer from a missing one.
    """
    return build_graph()
