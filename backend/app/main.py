"""FastAPI application: API routers plus (later) the built frontend."""

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.core.errors import NotFound

from app.core.config import VERSION
from app.core.errors import install_handlers
from app.core.web import install_security
from app.modules.documents.router import router as documents_router
from app.modules.events.router import router as events_router
from app.modules.parties.router import ROUTERS as parties_routers
from app.modules.sourcing.router import ROUTERS as sourcing_routers
from app.modules.catalog.router import ROUTERS as catalog_routers
from app.modules.costing.router import ROUTERS as costing_routers
from app.modules.search.router import router as search_router
from app.modules.system.router import router as system_router


def create_app() -> FastAPI:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = FastAPI(title="BOMS", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    install_handlers(app)
    install_security(app)
    app.include_router(system_router)
    app.include_router(events_router)
    app.include_router(documents_router)
    app.include_router(search_router)
    for router in parties_routers + sourcing_routers + catalog_routers + costing_routers:
        app.include_router(router)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": VERSION}

    mount_frontend(app)
    return app


def static_dir() -> Path:
    return Path(os.environ.get("BOMS_STATIC_DIR") or Path(__file__).resolve().parent / "static")


def mount_frontend(app: FastAPI) -> None:
    """Serve the built frontend (single-page app) from the same origin as the API."""
    root = static_dir().resolve()
    media_types = {".webmanifest": "application/manifest+json", ".js": "text/javascript", ".woff2": "font/woff2"}

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith("api/"):
            raise NotFound("not_found", "No such API endpoint")
        index = root / "index.html"
        if not index.is_file():
            raise NotFound("frontend_not_built", "Frontend is not built (run npm run build in frontend/)")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
            return FileResponse(candidate, media_type=media_types.get(candidate.suffix),
                                headers={"Cache-Control": cache})
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


app = create_app()
