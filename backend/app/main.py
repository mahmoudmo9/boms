"""FastAPI application: API routers plus (later) the built frontend."""

import logging

from fastapi import FastAPI

from app.core.config import VERSION
from app.core.errors import install_handlers
from app.core.web import install_security
from app.modules.documents.router import router as documents_router
from app.modules.events.router import router as events_router
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

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": VERSION}

    return app


app = create_app()
