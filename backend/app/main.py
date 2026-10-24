"""FastAPI application: API routers plus the built frontend, on 127.0.0.1:8765 only.

Run:  python -m app.main   (or uvicorn app.main:app --host 127.0.0.1 --port 8765)
"""

from fastapi import FastAPI

from app.core.config import VERSION, get_config
from app.core.errors import install_handlers
from app.core.web import CSRFMiddleware, HostCheckMiddleware
from app.modules.events.router import router as events_router
from app.modules.system.auth import router as auth_router
from app.modules.system.router import router as system_router


def create_app() -> FastAPI:
    app = FastAPI(title="BOMS", version=VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    install_handlers(app)
    for router in (auth_router, system_router, events_router):
        app.include_router(router)

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": VERSION}

    # Order: Host check runs first (outermost), then CSRF.
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(HostCheckMiddleware)
    return app


app = create_app()


def main() -> None:
    import uvicorn

    cfg = get_config()
    # Never bind to anything but loopback.
    uvicorn.run(app, host="127.0.0.1", port=cfg.http_port, proxy_headers=False, log_level="info")


if __name__ == "__main__":
    main()
