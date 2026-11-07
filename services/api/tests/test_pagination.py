import base64
import uuid
from datetime import UTC, datetime

import pytest

from ma_api.errors import ApiError
from ma_api.pagination import decode, encode


def test_a_cursor_comes_back_as_it_left() -> None:
    created_at = datetime(2026, 11, 7, 12, 0, 0, 123456, tzinfo=UTC)
    row_id = uuid.uuid4()
    assert decode(encode(created_at, row_id)) == (created_at, row_id)


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "not base64!",
        "é",
        base64.urlsafe_b64encode(b"\xff\xfe").decode(),
        base64.urlsafe_b64encode(b"not a date|not an id").decode(),
        base64.urlsafe_b64encode(b"2026-11-07T12:00:00+00:00|not an id").decode(),
        base64.urlsafe_b64encode(b"2026-11-07T12:00:00+00:00").decode(),
    ],
)
def test_a_bad_cursor_is_invalid(cursor: str) -> None:
    with pytest.raises(ApiError) as error:
        decode(cursor)
    assert (error.value.status, error.value.code) == (400, "invalid_request")
