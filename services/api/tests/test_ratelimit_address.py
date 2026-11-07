"""Which address counts, behind how many proxies. No database needed."""

import pytest
from starlette.requests import Request

from ma_api.ratelimit import client_address
from ma_api.settings import Settings


def request_from(host: str, forwarded: str | None) -> Request:
    headers = [] if forwarded is None else [(b"x-forwarded-for", forwarded.encode())]
    return Request({"type": "http", "headers": headers, "client": (host, 1234)})


def settings(proxies: int) -> Settings:
    return Settings(database_url="unused", trusted_proxy_count=proxies)


@pytest.mark.parametrize(
    ("proxies", "forwarded", "expected"),
    [
        # No trusted proxy: the header is the client's own words.
        (0, "1.1.1.1", "9.9.9.9"),
        # One proxy: it appended what it saw, the rest was sent by the client.
        (1, "1.1.1.1", "1.1.1.1"),
        (1, "6.6.6.6, 1.1.1.1", "1.1.1.1"),
        (1, " 6.6.6.6 ,  1.1.1.1 ", "1.1.1.1"),
        (2, "6.6.6.6, 1.1.1.1, 2.2.2.2", "1.1.1.1"),
        # Fewer entries than proxies, or none: not behind what was announced.
        (2, "1.1.1.1", "9.9.9.9"),
        (1, None, "9.9.9.9"),
        (1, "", "9.9.9.9"),
    ],
)
def test_the_address_that_counts(proxies: int, forwarded: str | None, expected: str) -> None:
    assert client_address(request_from("9.9.9.9", forwarded), settings(proxies)) == expected
