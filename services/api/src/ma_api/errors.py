"""The one error format of the API. Details name fields and rules, never the values received, which
can hold anything a stranger sent."""

import logging
import traceback
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("ma_api")


def error_response(
    status: int,
    code: str,
    details: Mapping[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = {
        "error": {"code": code, "message_key": f"errors.{code}", "details": dict(details or {})}
    }
    return JSONResponse(status_code=status, content=body, headers=dict(headers or {}))


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        details: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.details = details
        self.headers = headers


def not_found() -> ApiError:
    """Also what an owner gets for someone else's match: it must not reveal that it exists."""
    return ApiError(404, "not_found")


_STATUS_CODES = {
    401: "not_signed_in",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, error: ApiError) -> JSONResponse:
        return error_response(error.status, error.code, error.details, error.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid(_: Request, error: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(str(part) for part in item["loc"]), "rule": item["type"]}
            for item in error.errors()
        ]
        return error_response(400, "invalid_request", {"fields": fields})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, error: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(error.status_code, "internal")
        return error_response(error.status_code, code, None, error.headers)


def unexpected(request: Request, error: Exception) -> JSONResponse:
    """A crash: the answer says nothing, and the log says where, not what. The message and the
    traceback's values could quote what a stranger sent, so neither is written."""
    frames = traceback.extract_tb(error.__traceback__)
    place = f"{frames[-1].filename}:{frames[-1].lineno}" if frames else "unknown"
    log.error("unexpected %s on %s at %s", type(error).__name__, request.url.path, place)
    return error_response(500, "internal")
