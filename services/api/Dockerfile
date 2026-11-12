# The API. Build context: the repository root (`compose.yaml`). Pinned images, a non-root user, no
# build tool at run time. The migrations have their own image (db/Dockerfile).
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.14.4-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Every member of the workspace, for uv to resolve it; only the API gets installed.
COPY pyproject.toml uv.lock ./
COPY db/ db/
COPY packages/schemas/ packages/schemas/
COPY games/rocket-league/analysis/ games/rocket-league/analysis/
COPY services/api/ services/api/
COPY services/worker/ services/worker/
RUN uv sync --locked --no-dev --no-editable --package ma-api

FROM python:3.14.4-slim-bookworm
RUN useradd --create-home --uid 1000 app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
# Reached by the site only, on the compose network: never published.
CMD ["ma-api", "--host", "0.0.0.0", "--port", "8000"]
