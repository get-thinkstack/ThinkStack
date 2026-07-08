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

frontend_dist = settings.base_dir / "frontend" / "dist"
if frontend_dist.exists():
    # serve hashed build assets directly
    assets_dir = frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

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
            return FileResponse(str(candidate))
        return FileResponse(str(frontend_dist / "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
