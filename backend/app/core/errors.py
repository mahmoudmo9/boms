"""Application errors and their JSON representation.

Every error response has the shape ``{"error": {"code", "message", "details"}}``.
``code`` is a stable machine key the UI translates; ``message`` is English
for logs and developers.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("boms")


class AppError(Exception):
    status = 400

    def __init__(self, code: str, message: str = "", details: dict | None = None, status: int | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.details = details or {}
        if status is not None:
            self.status = status


class NotFound(AppError):
    status = 404


class Conflict(AppError):
    status = 409


class Unauthorized(AppError):
    status = 401


class Forbidden(AppError):
    status = 403


def error_body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        errors = [
            {"loc": [str(p) for p in e.get("loc", [])], "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(
            error_body("validation_error", "Invalid request", {"errors": errors}), status_code=422
        )

    @app.exception_handler(ValidationError)
    async def _model_validation(_: Request, exc: ValidationError):
        errors = [{"loc": [str(p) for p in e["loc"]], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return JSONResponse(error_body("validation_error", "Invalid data", {"errors": errors}), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return JSONResponse(error_body(f"http_{exc.status_code}", str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception):
        log.exception("Unhandled error")
        return JSONResponse(error_body("internal_error", "Internal error"), status_code=500)
