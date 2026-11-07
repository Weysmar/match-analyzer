"""Rate limits, counted in PostgreSQL: no Redis in V1.

A fixed window per key. An address never reaches the table in clear: it is personal data, and the
counters only need to tell two addresses apart.
"""

import hashlib
import hmac

from fastapi import Request

from ma_api.db import Connection
from ma_api.errors import ApiError
from ma_api.settings import Settings


def client_address(request: Request, settings: Settings) -> str:
    """The address the last trusted proxy saw. Anything further left in `X-Forwarded-For` comes from
    the client, who can write what they like: reading it would let them dodge every limit."""
    direct = request.client.host if request.client else "unknown"
    if settings.trusted_proxy_count == 0:
        return direct
    header = request.headers.get("x-forwarded-for", "")
    forwarded = [part.strip() for part in header.split(",") if part.strip()]
    if len(forwarded) < settings.trusted_proxy_count:
        return direct
    return forwarded[-settings.trusted_proxy_count]


def address_key(request: Request, settings: Settings, scope: str) -> str:
    """Per limit: the windows of two limits can start at the same instant, and would add up."""
    address = client_address(request, settings)
    digest = hmac.new(settings.session_secret.encode(), address.encode(), hashlib.sha256)
    return f"{scope}:ip:{digest.hexdigest()}"


def hit(connection: Connection, key: str, limit: int, window_s: int) -> None:
    """Counts a request, and refuses it past `limit` in the current window.

    Call it first in a route: it commits. The count has to survive whatever follows, or a failed
    sign-in would roll its own attempt back and never reach the limit. It also frees the counter's
    row at once, instead of making requests on the same key wait for each other's end.
    """
    row = connection.execute(
        """
        INSERT INTO rate_limit_buckets (bucket_key, window_start, hits)
        VALUES (%(key)s, date_bin(make_interval(secs => %(window)s), now(), 'epoch'), 1)
        ON CONFLICT (bucket_key, window_start)
        DO UPDATE SET hits = rate_limit_buckets.hits + 1
        RETURNING hits,
                  ceil(extract(epoch FROM window_start + make_interval(secs => %(window)s) - now()))
        """,
        {"key": key, "window": window_s},
    ).fetchone()
    assert row is not None
    connection.commit()
    if row[0] > limit:
        retry = max(int(row[1]), 1)
        raise ApiError(429, "rate_limited", {"retry_after_s": retry}, {"Retry-After": str(retry)})


def limit_auth(connection: Connection, request: Request, settings: Settings) -> None:
    key = address_key(request, settings, "auth")
    hit(connection, key, settings.rate_auth_ip_per_minute, 60)
