"""`ma-api`: serves the API. It stays behind the site's reverse proxy."""

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="ma-api", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    # The proxy headers are read in `ma_api.ratelimit`, by a rule of our own.
    uvicorn.run(
        "ma_api.app:create_app",
        factory=True,
        host=arguments.host,
        port=arguments.port,
        proxy_headers=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
