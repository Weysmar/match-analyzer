"""The object store, for real. Needs `just dev-up`."""

import os
import uuid
from pathlib import Path

import boto3
import pytest
from botocore.config import Config

from ma_worker.settings import Settings
from ma_worker.store import S3Store, StoreError, TooLargeError

pytestmark = pytest.mark.s3

BODY = b"some bytes" * 1000


@pytest.fixture
def store() -> S3Store:
    endpoint = os.environ.get("S3_ENDPOINT")
    if not endpoint:
        pytest.skip("S3_ENDPOINT is not set: run `just dev-up`, then `just test-s3`")
    return S3Store(
        Settings(
            database_url="unused",
            s3_endpoint=endpoint,
            s3_region=os.environ.get("S3_REGION", "us-east-1"),
            s3_bucket=os.environ["S3_BUCKET"],
            s3_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
            s3_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        )
    )


@pytest.fixture
def key() -> str:
    return f"test-worker/{uuid.uuid4()}"


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "source.bin"
    path.write_bytes(BODY)
    return path


def content_type_of(key: str) -> str:
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    head = client.head_object(Bucket=os.environ["S3_BUCKET"], Key=key)
    content_type: str = head["ContentType"]
    return content_type


def test_a_file_goes_there_and_back(store: S3Store, key: str, source: Path, tmp_path: Path) -> None:
    store.upload(source, key, "application/octet-stream")
    assert store.size(key) == len(BODY)
    assert content_type_of(key) == "application/octet-stream"
    target = tmp_path / "target.bin"
    store.download(key, target, len(BODY))
    assert target.read_bytes() == BODY
    store.delete(key)


def test_a_missing_object_has_no_size(store: S3Store, key: str) -> None:
    assert store.size(key) is None


def test_a_missing_object_cannot_be_downloaded(store: S3Store, key: str, tmp_path: Path) -> None:
    target = tmp_path / "target.bin"
    with pytest.raises(StoreError):
        store.download(key, target, 100)
    assert not target.exists()


def test_a_download_stops_at_the_limit(
    store: S3Store, key: str, source: Path, tmp_path: Path
) -> None:
    store.upload(source, key, "application/octet-stream")
    target = tmp_path / "target.bin"
    with pytest.raises(TooLargeError):
        store.download(key, target, len(BODY) - 1)
    assert not target.exists()
    store.delete(key)


def test_copying_keeps_the_content(store: S3Store, key: str, source: Path, tmp_path: Path) -> None:
    other = f"{key}-copy"
    store.upload(source, key, "application/octet-stream")
    store.copy(key, other)
    target = tmp_path / "target.bin"
    store.download(other, target, len(BODY))
    assert target.read_bytes() == BODY
    assert store.size(key) == len(BODY)
    store.delete(key)
    store.delete(other)


def test_copying_nothing_fails(store: S3Store, key: str) -> None:
    with pytest.raises(StoreError):
        store.copy(key, f"{key}-copy")


def test_deleting_twice_is_fine(store: S3Store, key: str, source: Path) -> None:
    store.upload(source, key, "application/octet-stream")
    store.delete(key)
    assert store.size(key) is None
    store.delete(key)
