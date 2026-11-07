"""What the API asks of the object store, without one. A real one is in test_uploads_s3.py."""

import httpx2
import pytest

from ma_api.errors import ApiError
from ma_api.settings import Settings
from ma_api.storage import S3Storage

SECRET = "the-secret-key"


def storage(**overrides: str) -> S3Storage:
    values = {
        "database_url": "unused",
        "s3_endpoint": "http://127.0.0.1:1",
        "s3_public_endpoint": "http://public.test:9000",
        "s3_region": "us-east-1",
        "s3_bucket": "a-bucket",
        "s3_access_key_id": "the-access-key",
        "s3_secret_access_key": SECRET,
    }
    return S3Storage(Settings(**values | overrides))  # type: ignore[arg-type]


def test_a_url_holds_its_conditions_and_no_secret() -> None:
    url = httpx2.URL(storage().presign_put("incoming/an-id", 1234))
    assert url.host == "public.test"
    assert url.path == "/a-bucket/incoming/an-id"
    assert url.params["X-Amz-Expires"] == "600"
    # Part of the signature: the store refuses another size or another type.
    signed = url.params["X-Amz-SignedHeaders"].split(";")
    assert "content-length" in signed
    assert "content-type" in signed
    assert SECRET not in str(url)


def test_without_a_public_endpoint_the_url_uses_the_other_one() -> None:
    url = httpx2.URL(storage(s3_public_endpoint="").presign_put("incoming/an-id", 1))
    assert url.host == "127.0.0.1"


def test_a_store_out_of_reach_is_unavailable() -> None:
    with pytest.raises(ApiError) as error:
        storage().object_size("incoming/an-id")
    assert (error.value.status, error.value.code) == (503, "unavailable")


def test_no_store_configured_is_unavailable() -> None:
    with pytest.raises(ApiError) as error:
        storage(s3_endpoint="", s3_public_endpoint="").presign_put("incoming/an-id", 1)
    assert (error.value.status, error.value.code) == (503, "unavailable")
