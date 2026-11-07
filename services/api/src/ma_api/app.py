"""The API's application."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx2
import psycopg
from fastapi import FastAPI, Request, Response
from psycopg_pool import PoolTimeout

from ma_api import __version__, account, epic, errors, matches, sessions, stats, steam, uploads
from ma_api.db import Database
from ma_api.errors import error_response
from ma_api.settings import PREFIX, Settings
from ma_api.storage import ObjectStore, S3Storage

_HTTP_TIMEOUT_S = 10.0
# Replays go straight to the object store: what reaches the API is small.
_BODY_MAX_BYTES = 1_048_576
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # Responses hold personal data: no cache keeps them.
    "Cache-Control": "no-store",
}


def _body_too_large(request: Request) -> bool:
    """On what the request announces: a body without a stated length is refused as well."""
    if "transfer-encoding" in request.headers:
        return True
    length = request.headers.get("content-length", "0")
    return not length.isdecimal() or int(length) > _BODY_MAX_BYTES


def create_app(
    settings: Settings | None = None,
    *,
    http_transport: httpx2.BaseTransport | None = None,
    storage: ObjectStore | None = None,
) -> FastAPI:
    """`http_transport` and `storage` replace the outside world in the tests."""
    settings = settings or Settings.from_env()
    database = Database(settings.database_url, timeout_s=settings.database_timeout_s)
    http = httpx2.Client(transport=http_transport, timeout=_HTTP_TIMEOUT_S)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database.open()
        yield
        http.close()
        database.close()

    # The documentation is a development aid: production does not advertise its routes.
    app = FastAPI(
        title="match-analyzer",
        version=__version__,
        lifespan=lifespan,
        docs_url=None if settings.production else "/api/docs",
        redoc_url=None,
        openapi_url=None if settings.production else f"{PREFIX}/openapi.json",
    )
    app.state.settings = settings
    app.state.database = database
    app.state.http = http
    app.state.storage = storage or S3Storage(settings)
    errors.install(app)

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Cookies travel with cross-site requests: anything that changes data must come from the
        # site itself. Browsers always send Origin on these methods.
        if (
            request.method not in _SAFE_METHODS
            and request.headers.get("origin") != settings.site_origin
        ):
            response: Response = error_response(403, "bad_origin")
        elif request.method not in _SAFE_METHODS and _body_too_large(request):
            response = error_response(413, "too_large")
        else:
            # Caught here rather than by an exception handler: Starlette would run that one outside
            # this middleware, then raise again, and the server would log the whole traceback.
            try:
                response = await call_next(request)
            except Exception as error:
                response = errors.unexpected(request, error)
        for name, value in _HEADERS.items():
            response.headers.setdefault(name, value)
        if settings.secure_cookies:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

    @app.get("/health")
    def health() -> Response:
        """Whether the API can reach its database. Says nothing else about it."""
        try:
            with database.transaction() as connection:
                connection.execute("SELECT 1")
        except psycopg.Error, PoolTimeout:
            return error_response(503, "unavailable")
        return Response('{"status":"ok"}', media_type="application/json")

    app.include_router(sessions.router, prefix=PREFIX)
    app.include_router(steam.router, prefix=PREFIX)
    app.include_router(epic.router, prefix=PREFIX)
    app.include_router(uploads.router, prefix=PREFIX)
    app.include_router(matches.router, prefix=PREFIX)
    app.include_router(stats.router, prefix=PREFIX)
    app.include_router(account.router, prefix=PREFIX)
    return app
