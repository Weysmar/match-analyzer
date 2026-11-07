"""The object store, as the worker needs it."""

from functools import cached_property
from pathlib import Path
from typing import Protocol

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from ma_worker.settings import Settings

_MISSING = {"404", "NoSuchKey", "NotFound"}
_CHUNK_BYTES = 1_048_576


class StoreError(Exception):
    """The store did not do what was asked. The job can try again later."""


class TooLargeError(Exception):
    """The object holds more than the caller accepts."""


class ObjectStore(Protocol):
    def size(self, key: str) -> int | None: ...

    def download(self, key: str, destination: Path, max_bytes: int) -> None: ...

    def upload(self, source: Path, key: str, content_type: str) -> None: ...

    def copy(self, source_key: str, key: str) -> None: ...

    def delete(self, key: str) -> None: ...


class S3Store:
    """Everything happens in the calling thread, on purpose: the sandbox forks, which is only safe
    with no other thread running. So no `upload_file`, whose transfers use a pool of threads."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @cached_property
    def _client(self) -> BaseClient:
        if not self._settings.s3_endpoint:
            raise StoreError("no object store configured")
        return boto3.client(
            "s3",
            endpoint_url=self._settings.s3_endpoint,
            region_name=self._settings.s3_region,
            aws_access_key_id=self._settings.s3_access_key_id,
            aws_secret_access_key=self._settings.s3_secret_access_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                connect_timeout=5,
                read_timeout=60,
                retries={"total_max_attempts": 3},
            ),
        )

    @property
    def _bucket(self) -> str:
        return self._settings.s3_bucket

    def size(self, key: str) -> int | None:
        """The object's size, or None when it is not there."""
        try:
            head = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in _MISSING:
                return None
            raise StoreError(key) from error
        except BotoCoreError as error:
            raise StoreError(key) from error
        size: int = head["ContentLength"]
        return size

    def download(self, key: str, destination: Path, max_bytes: int) -> None:
        """Stops at `max_bytes`, whatever the store said beforehand: the file comes from a stranger.
        Leaves nothing behind when it fails."""
        try:
            body = self._client.get_object(Bucket=self._bucket, Key=key)["Body"]
            written = 0
            with destination.open("wb") as output:
                for chunk in body.iter_chunks(_CHUNK_BYTES):
                    written += len(chunk)
                    if written > max_bytes:
                        raise TooLargeError(key)
                    output.write(chunk)
        except TooLargeError:
            destination.unlink(missing_ok=True)
            raise
        except (ClientError, BotoCoreError, OSError) as error:
            destination.unlink(missing_ok=True)
            raise StoreError(key) from error

    def upload(self, source: Path, key: str, content_type: str) -> None:
        try:
            with source.open("rb") as body:
                self._client.put_object(
                    Bucket=self._bucket, Key=key, Body=body, ContentType=content_type
                )
        except (ClientError, BotoCoreError) as error:
            raise StoreError(key) from error

    def copy(self, source_key: str, key: str) -> None:
        try:
            self._client.copy_object(
                Bucket=self._bucket,
                Key=key,
                CopySource={"Bucket": self._bucket, "Key": source_key},
            )
        except (ClientError, BotoCoreError) as error:
            raise StoreError(key) from error

    def delete(self, key: str) -> None:
        """Deleting what is not there is fine: a job may run twice."""
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (ClientError, BotoCoreError) as error:
            raise StoreError(key) from error
