# The database's own image: the migrations (`ma-db upgrade`) and the backups (`ma-db backup`,
# `ma-db restore`, T9.7). Build context: the repository root (`compose.yaml`). pg_dump must be at
# least the server's version (16): Debian bookworm only has 15, so the client comes from
# PostgreSQL's own repository. Pinned images, a non-root user, no build tool at run time.
FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.14.4-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY db/ db/
COPY packages/schemas/ packages/schemas/
COPY games/rocket-league/analysis/ games/rocket-league/analysis/
COPY services/api/ services/api/
COPY services/worker/ services/worker/
RUN uv sync --locked --no-dev --no-editable --package ma-db

FROM python:3.14.4-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && install -d /usr/share/postgresql-common/pgdg \
 && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    https://www.postgresql.org/media/keys/ACCC4CF8.asc \
 && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
    > /etc/apt/sources.list.d/pgdg.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends postgresql-client-16 \
 && apt-get purge -y curl \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 app
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER app
CMD ["ma-db", "upgrade"]
