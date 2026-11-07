"""Cursors for lists ordered by newest first. Rows created together share a time, so the id settles
their order. A cursor means nothing to the client and grants nothing: each query still filters on
its owner."""

import base64
import binascii
import uuid
from datetime import datetime

from ma_api.errors import ApiError


def encode(created_at: datetime, row_id: uuid.UUID) -> str:
    text = f"{created_at.isoformat()}|{row_id}"
    return base64.urlsafe_b64encode(text.encode()).decode()


def decode(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        created_at, _, row_id = base64.urlsafe_b64decode(cursor).decode().partition("|")
        return datetime.fromisoformat(created_at), uuid.UUID(row_id)
    except binascii.Error, UnicodeDecodeError, ValueError:
        fields = [{"field": "query.cursor", "rule": "invalid_cursor"}]
        raise ApiError(400, "invalid_request", {"fields": fields}) from None
