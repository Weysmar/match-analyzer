"""The API's application."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request, Response
from psycopg_pool import PoolTimeout

from ma_api import __version__, errors, sessions
from ma_api.db import Database
from ma_api.errors import error_response
from ma_api.settings import Settings

PREFIX = "/api/v1"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    # Responses hold personal data: no cache keeps them.
    "Cache-Control": "no-store",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_url, timeout_s=settings.database_timeout_s)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        database.open()
        yield
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
    return app
