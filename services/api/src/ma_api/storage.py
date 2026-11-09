"""The object store, as far as the API touches it: it never relays a replay's bytes."""

from functools import cached_property
from typing import Protocol

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from ma_api.errors import ApiError
from ma_api.settings import Settings

CONTENT_TYPE = "application/octet-stream"
_MISSING = {"404", "NoSuchKey", "NotFound"}


class ObjectStore(Protocol):
    def presign_put(self, key: str, size: int) -> str: ...

    def object_size(self, key: str) -> int | None: ...

    def presign_get(self, key: str, ttl_s: int) -> str: ...


def _unavailable() -> ApiError:
    return ApiError(503, "unavailable")


class S3Storage:
    """Clients are built on first use: most of the API never needs them."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _client(self, endpoint: str) -> BaseClient:
        if not endpoint:
            raise _unavailable()
        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=self._settings.s3_region,
            aws_access_key_id=self._settings.s3_access_key_id,
            aws_secret_access_key=self._settings.s3_secret_access_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                connect_timeout=5,
                read_timeout=10,
                retries={"total_max_attempts": 2},
            ),
        )

    @cached_property
    def _api(self) -> BaseClient:
        return self._client(self._settings.s3_endpoint)

    @cached_property
    def _signer(self) -> BaseClient:
        # URLs name their host: this is the one the browser can reach.
        return self._client(self._settings.s3_public_endpoint or self._settings.s3_endpoint)

    def presign_put(self, key: str, size: int) -> str:
        """A short-lived URL for exactly this key, this size and this type. The store refuses any
        other body, which the presigned PUT would not do by itself without `Content-Length`."""
        url: str = self._signer.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self._settings.s3_bucket,
                "Key": key,
                "ContentType": CONTENT_TYPE,
                "ContentLength": size,
            },
            ExpiresIn=self._settings.upload_url_ttl_s,
        )
        return url

    def presign_get(self, key: str, ttl_s: int) -> str:
        """A short-lived URL to read this one object, such as a match's 2D view."""
        url: str = self._signer.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._settings.s3_bucket, "Key": key},
            ExpiresIn=ttl_s,
        )
        return url

    def object_size(self, key: str) -> int | None:
        """The object's size, or None when it is not there."""
        try:
            head = self._api.head_object(Bucket=self._settings.s3_bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in _MISSING:
                return None
            raise _unavailable() from error
        except BotoCoreError as error:
            raise _unavailable() from error
        size: int = head["ContentLength"]
        return size
