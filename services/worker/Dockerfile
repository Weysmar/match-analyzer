# The worker, with the parser `rl-parse` it runs in its sandbox. Build context: the repository root
# (`compose.yaml`). Pinned images, a non-root user, no compiler at run time.
FROM rust:1.99.1-slim-bookworm AS parser
WORKDIR /src
COPY games/rocket-league/parser/Cargo.toml games/rocket-league/parser/Cargo.lock ./
COPY games/rocket-league/parser/src ./src
RUN cargo build --release --locked --bin rl-parse

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
RUN uv sync --locked --no-dev --no-editable --package ma-worker

FROM python:3.14.4-slim-bookworm
RUN useradd --create-home --uid 1000 worker
COPY --from=parser /src/target/release/rl-parse /usr/local/bin/rl-parse
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PARSER_BIN=rl-parse
USER worker
CMD ["ma-worker", "run"]
