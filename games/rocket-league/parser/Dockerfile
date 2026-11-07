# The rl-parse binary alone. Build context: this directory.
FROM rust:1.99.1-slim-bookworm AS build
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY src ./src
RUN cargo build --release --locked --bin rl-parse

FROM debian:bookworm-slim
COPY --from=build /src/target/release/rl-parse /usr/local/bin/rl-parse
RUN useradd --create-home --uid 1000 parser
USER parser
ENTRYPOINT ["rl-parse"]
