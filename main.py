"""The backend process: one FastAPI app on 127.0.0.1 serving /api and the built
interface.

Started by the desktop shell (src-tauri/src/lib.rs) as the frozen
`thinkstack-api` binary, or by `scripts/dev.sh` from source. In order:

    1. before any import of llama.cpp: probe and select the GPU engine
    2. register MIME types (Windows), build the app, CORS for the dev server
    3. mount every router under /api/<prefix>
    4. serve frontend/dist: hashed assets cached forever, index.html never
    5. lifespan: data dirs, seed + reconcile models, open the vector store,
       start the background job queue (stopped on shutdown)
"""

import logging
import sys
import mimetypes
from contextlib import asynccontextmanager

# ── before anything imports llama.cpp ───────────────────────────────────────
# Two things have to happen at the very top of this file, ahead of every other
# import, because both are about which shared library llama.cpp will load and
# that is decided the first time it is imported.
#
# 1. The probe. A separate process asks whether downloaded GPU libraries can
#    actually load. It has to answer and exit before the application exists,
#    since the whole point is that it is allowed to crash where the backend is
#    not.
# 2. The override. If a previous activation was verified, LLAMA_CPP_LIB_PATH is
#    set now -- llama_cpp reads it at import, and every import of it in this
#    codebase is inside a function, so this is early enough.
from config import settings  # noqa: E402  - must precede the accel import
from infrastructure import acceleration  # noqa: E402

if acceleration.PROBE_FLAG in sys.argv:
    _i = sys.argv.index(acceleration.PROBE_FLAG)
    _dir = sys.argv[_i + 1] if len(sys.argv) > _i + 1 else ""
    raise SystemExit(acceleration.run_probe(_dir))

acceleration.apply_override(settings.data_dir)
# ────────────────────────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from domain.paper_writer.compiler import ProjectIdError
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def register_web_mime_types() -> None:
    """Serve .js/.mjs as JavaScript on every OS (defect D-16).

    On Windows, `mimetypes` is seeded from the registry, which often lacks
    `.mjs` or maps `.js` to text/plain; Starlette then serves the PDF viewer's
    worker as text/plain and the browser refuses to run it. Invisible on Linux
    and macOS. Called at import, because StaticFiles can answer as soon as the
    app exists.
    """
    for suffix, kind in (
        (".mjs", "text/javascript"),
        (".js", "text/javascript"),
        (".css", "text/css"),
        (".json", "application/json"),
        (".svg", "image/svg+xml"),
        (".wasm", "application/wasm"),
    ):
        mimetypes.add_type(kind, suffix)


register_web_mime_types()

from infrastructure.file_manager import ensure_directories
from infrastructure.jobs import job_queue
from infrastructure.local_vector_store import get_vector_store
from api.routes_documents import router as documents_router
from api.routes_search import router as search_router
from api.routes_graph import router as graph_router
from api.routes_analysis import router as analysis_router
from api.routes_gaps import router as gaps_router
from api.routes_system import router as system_router
from api.routes_encryption import router as encryption_router
from api.routes_papers import router as papers_router
from api.routes_paper_files import router as paper_files_router
from api.routes_citations import router as citations_router
from api.routes_models import router as models_router
from api.routes_hf import router as hf_router
from api.routes_registry import router as registry_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("thinkstack")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown; see step 5 in the module docstring."""
    logger.info("initializing thinkstack")
    ensure_directories()
    get_vector_store()
    # started here rather than at import so the worker binds to the loop that
    # actually serves requests.
    job_queue.start()
    logger.info("thinkstack ready at http://%s:%s", settings.host, settings.port)
    yield
    logger.info("shutting down thinkstack")
    await job_queue.stop()


app = FastAPI(
    title="thinkstack",
    description="offline edge-ai research assistant with local inference",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: only the Vite dev server (3001) is a permitted cross-origin caller.
# Production is same-origin (the window loads the UI from this server).
#
# Any web page the user opens can SEND requests to 127.0.0.1; CORS only stops
# it READING the reply. Never widen this to "*": that let any page read the
# library and Scribe projects. Blind "simple" writes are stopped separately,
# by _refuse_foreign_writes below. No cookies, so no credentials.
DEV_ORIGINS = [
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]

# A refused project id (compiler._get_project_dir) is a 404 everywhere,
# handled once here: routes caught it inconsistently, and a 500 echoed the
# attempted path to the caller. 404, not 400, so a probe learns nothing.
@app.exception_handler(ProjectIdError)
async def _bad_project_id(request, exc):        # noqa: ARG001 - signature is fastapi's
    return JSONResponse(status_code=404, content={"detail": "project not found"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The other half of the CORS note above: a foreign page can still SEND a
# simple request (multipart, or no body) blind. Browsers always attach Origin
# to a cross-site write, so a write whose Origin is not the app or the dev
# server is refused before any route runs. No Origin means not a browser
# (curl, tests, the bundle validator). GETs stay CORS's job: the loading
# screen polls from tauri:// with GET.
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_OWN_ORIGINS = {
    f"http://{settings.host}:{settings.port}",
    f"http://127.0.0.1:{settings.port}",
    f"http://localhost:{settings.port}",
    *DEV_ORIGINS,
}


@app.middleware("http")
async def _refuse_foreign_writes(request, call_next):
    origin = request.headers.get("origin")
    if request.method in _WRITE_METHODS and origin is not None and origin not in _OWN_ORIGINS:
        return JSONResponse(status_code=403, content={"detail": "cross-origin write refused"})
    return await call_next(request)

app.include_router(documents_router, prefix="/api/documents", tags=["documents"])
app.include_router(search_router, prefix="/api/search", tags=["search"])
app.include_router(graph_router, prefix="/api/graph", tags=["graph"])
app.include_router(analysis_router, prefix="/api/analysis", tags=["analysis"])
app.include_router(gaps_router, prefix="/api/gaps", tags=["gaps"])
app.include_router(system_router, prefix="/api/system", tags=["system"])
app.include_router(encryption_router, prefix="/api/encryption", tags=["encryption"])
app.include_router(papers_router, prefix="/api/papers", tags=["papers"])
# The files inside a project. Same prefix on purpose: a project's files are part
# of the project, not a separate resource.
app.include_router(paper_files_router, prefix="/api/papers", tags=["papers"])
# Citing the library from inside a project -- also part of the project.
app.include_router(citations_router, prefix="/api/papers", tags=["papers"])
app.include_router(models_router, prefix="/api/models", tags=["models"])
# the registry shares the /api/models prefix on purpose: it is the same
# resource, split across two modules because setup and management are
# different jobs with different consequences.
app.include_router(registry_router, prefix="/api/models", tags=["models"])
# Hugging Face, under its own prefix so the internet calls are obvious from
# the URL. (Catalog downloads and the GPU engine also download, on request.)
app.include_router(hf_router, prefix="/api/hf", tags=["huggingface"])

frontend_dist = settings.base_dir / "frontend" / "dist"

# Caching: /assets forever, index.html NEVER.
#
# The webview's HTTP cache outlives the app (an update replaces the binary,
# not the cache), and without headers WebKit reuses responses heuristically.
# A stale index.html points at the previous build's assets, so an updated app
# shows the old UI and old version number. Vite content-hashes /assets, so
# those can never be stale.
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
