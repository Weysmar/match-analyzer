"""The memory of a sign-in and where it may lead. No database needed."""

import pytest

from ma_api.flow import Flow, decode, encode, safe_return_to
from ma_api.settings import Settings

SETTINGS = Settings(database_url="unused", session_secret="one secret")
FLOW = Flow("the-nonce", "/mine")
NOW = 1_000_000.0


def test_a_flow_comes_back_as_it_left() -> None:
    assert decode(SETTINGS, encode(SETTINGS, FLOW, NOW + 1), NOW) == FLOW


def test_a_flow_expires() -> None:
    assert decode(SETTINGS, encode(SETTINGS, FLOW, NOW), NOW) is None


def test_another_secret_is_refused() -> None:
    other = Settings(database_url="unused", session_secret="another secret")
    assert decode(other, encode(SETTINGS, FLOW, NOW + 1), NOW) is None


def test_a_rewritten_flow_is_refused() -> None:
    forged = encode(SETTINGS, Flow("the-nonce", "//evil.test"), NOW + 1).partition(".")[0]
    signature = encode(SETTINGS, FLOW, NOW + 1).partition(".")[2]
    assert decode(SETTINGS, f"{forged}.{signature}", NOW) is None


@pytest.mark.parametrize("cookie", ["", "nothing", ".", "a.b", "é.é"])
def test_garbage_is_refused(cookie: str) -> None:
    assert decode(SETTINGS, cookie, NOW) is None


@pytest.mark.parametrize("value", ["/", "/mine", "/matches/12?tab=boost#top", "/%2f%2fevil.test"])
def test_pages_of_this_site_are_accepted(value: str) -> None:
    assert safe_return_to(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "mine",
        "https://evil.test",
        "//evil.test",
        "/\\evil.test",
        "\\\\evil.test",
        "/\t/evil.test",
        "/\n/evil.test",
        "/" + "x" * 512,
    ],
)
def test_anything_else_is_refused(value: str) -> None:
    assert safe_return_to(value) is None
