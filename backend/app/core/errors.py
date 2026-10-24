"""Application errors and their JSON representation: {"error": {"code", "message", ...}}."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status = 400
    code = "bad_request"

    def __init__(self, message: str = "", code: str | None = None, status: int | None = None, **extra):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status:
            self.status = status
        self.extra = extra


class NotFound(AppError):
    status = 404
    code = "not_found"


class Conflict(AppError):
    status = 409
    code = "conflict"


class Unauthorized(AppError):
    status = 401
    code = "unauthorized"


class Forbidden(AppError):
    status = 403
    code = "forbidden"


def error_body(code: str, message: str, **extra) -> dict:
    return {"error": {"code": code, "message": message, **extra}}


def install_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(error_body(exc.code, exc.message, **exc.extra), status_code=exc.status)
