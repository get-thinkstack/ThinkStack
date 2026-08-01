"""
thinkstack application entry point.

configures and starts the fastapi server with all api routers,
static file serving for the react frontend, cors middleware,
and startup/shutdown lifecycle events.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from infrastructure.file_manager import ensure_directories
from infrastructure.local_vector_store import get_vector_store
from api.routes_documents import router as documents_router
from api.routes_search import router as search_router
from api.routes_analysis import router as analysis_router
from api.routes_gaps import router as gaps_router
from api.routes_system import router as system_router
from api.routes_chat import router as chat_router
from api.routes_encryption import router as encryption_router
from api.routes_papers import router as papers_router
from api.routes_models import router as models_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("thinkstack")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """handle startup and shutdown tasks."""
    logger.info("initializing thinkstack")
    ensure_directories()
    get_vector_store()
    logger.info("thinkstack ready at http://%s:%s", settings.host, settings.port)
    yield
    logger.info("shutting down thinkstack")


app = FastAPI(
    title="thinkstack",
    description="offline edge-ai research assistant with local inference",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router, prefix="/api/documents", tags=["documents"])
app.include_router(search_router, prefix="/api/search", tags=["search"])
app.include_router(analysis_router, prefix="/api/analysis", tags=["analysis"])
app.include_router(gaps_router, prefix="/api/gaps", tags=["gaps"])
app.include_router(system_router, prefix="/api/system", tags=["system"])
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])
app.include_router(encryption_router, prefix="/api/encryption", tags=["encryption"])
app.include_router(papers_router, prefix="/api/papers", tags=["papers"])
app.include_router(models_router, prefix="/api/models", tags=["models"])

frontend_dist = settings.base_dir / "frontend" / "dist"

# Caching rules for the bundled UI, and why they are not optional.
#
# The desktop shell is a WebKit view pointed at http://127.0.0.1:8000, and it
# keeps an HTTP cache that OUTLIVES the application: updating the app replaces
# the binary, not the webview's cache. Nothing here sent any cache header, so
# WebKit applied *heuristic* freshness -- with no Cache-Control it may reuse a
# response for a fraction of its age without revalidating at all.
#
# index.html is the file that breaks: its name never changes, so a stale copy
# keeps referencing the PREVIOUS build's asset filenames. An updated app then
# renders the old UI, reports the old __APP_VERSION__ in the sidebar, and looks
# for all the world like the update never installed. That is exactly what was
# reported after 1.6.8 shipped -- a freshly downloaded build still showing
# v1.6.7 and the old two-button Analysis screen.
#
# Vite content-hashes everything under /assets (index-B4FzKC14.js), so a new
# build is always a new URL and can never be served stale. Those are safe to
# cache permanently; index.html must never be cached.
INDEX_CACHE = "no-store, no-cache, must-revalidate, max-age=0"
ASSET_CACHE = "public, max-age=31536000, immutable"


class _ImmutableAssets(StaticFiles):
    """StaticFiles for content-hashed bundles: cache forever, safely."""

    def is_not_modified(self, response_headers, request_headers) -> bool:
        response_headers.setdefault("cache-control", ASSET_CACHE)
        return super().is_not_modified(response_headers, request_headers)

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers.setdefault("cache-control", ASSET_CACHE)
        return response


if frontend_dist.exists() and (frontend_dist / "index.html").exists():
    # serve hashed build assets directly
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", _ImmutableAssets(directory=str(assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        """serve the SPA: real files when present, else index.html.

        client-side routes (e.g. /analysis, /write) and a hard refresh on
        them fall back to index.html instead of 404ing. api paths are left
        to their routers.
        """
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="not found")
        candidate = frontend_dist / full_path
        if full_path and candidate.is_file():
            # A hashed asset can be cached forever; anything else (favicon,
            # manifest, and index.html itself) must not be, because its name
            # is stable across builds.
            cache = ASSET_CACHE if full_path.startswith("assets/") else INDEX_CACHE
            return FileResponse(str(candidate), headers={"Cache-Control": cache})
        return FileResponse(
            str(frontend_dist / "index.html"),
            headers={"Cache-Control": INDEX_CACHE},
        )

if __name__ == "__main__":
    import argparse
    import multiprocessing
    import sys

    import uvicorn

    # pyinstaller re-executes the bundle for every child process; without this
    # a frozen build that spawns one would boot a second copy of the whole app.
    multiprocessing.freeze_support()

    parser = argparse.ArgumentParser(description="thinkstack backend server")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args()

    frozen = getattr(sys, "frozen", False)

    # the reloader works by respawning the interpreter and watching source
    # files on disk. a frozen build has neither, so enabling it there spawns a
    # broken child and the server never comes up -- only ever reload from
    # source. passing the app object directly (rather than "main:app") also
    # avoids a re-import of __main__ inside the bundle.
    uvicorn.run(
        app if frozen else "main:app",
        host=args.host,
        port=args.port,
        reload=settings.debug and not frozen,
    )
