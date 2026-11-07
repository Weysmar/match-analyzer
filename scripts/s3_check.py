"""Checks the S3 behavior uploads rely on, against the store configured in the environment.

Used to choose the development emulator (T1.4), and again on R2 before production (T9.4): a
presigned PUT must refuse a body larger than declared, a wrong content type and an expired URL.
"""

import http.client
import os
import sys
import time
import urllib.parse
import uuid
from dataclasses import dataclass

import boto3
from botocore.client import BaseClient
from botocore.config import Config

ALLOWED_ORIGIN = "http://localhost:3000"
OTHER_ORIGIN = "http://evil.test"
CONTENT_TYPE = "application/octet-stream"
BODY = b"x" * 100


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


def send(url: str, method: str, headers: dict[str, str], body: bytes = b"") -> Response:
    """Sends the request as written: the stated Content-Length is the body's real length."""
    parts = urllib.parse.urlsplit(url)
    target = f"{parts.path}?{parts.query}" if parts.query else parts.path
    kind = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    connection = kind(parts.netloc, timeout=15)
    try:
        connection.request(method, target, body=body, headers=headers)
        response = connection.getresponse()
        return Response(
            response.status,
            {name.lower(): value for name, value in response.getheaders()},
            response.read(),
        )
    except OSError:
        return Response(0, {}, b"")
    finally:
        connection.close()


def client(endpoint: str) -> BaseClient:
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=os.environ.get("S3_REGION", "auto"),
        aws_access_key_id=os.environ["S3_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["S3_SECRET_ACCESS_KEY"],
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def presign(signer: BaseClient, bucket: str, key: str, expires: int = 600) -> str:
    url: str = signer.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": bucket,
            "Key": key,
            "ContentType": CONTENT_TYPE,
            "ContentLength": len(BODY),
        },
        ExpiresIn=expires,
    )
    return url


def main() -> int:
    bucket = os.environ["S3_BUCKET"]
    api = client(os.environ["S3_ENDPOINT"])
    signer = client(os.environ.get("S3_PUBLIC_ENDPOINT") or os.environ["S3_ENDPOINT"])
    run = uuid.uuid4().hex
    incoming = f"incoming/{run}"
    raw = f"raw/{run}.replay"
    results: list[tuple[str, bool, str]] = []

    def check(name: str, passed: bool, detail: object = "") -> None:
        results.append((name, passed, str(detail)))

    headers = {"Content-Type": CONTENT_TYPE}

    url = presign(signer, bucket, incoming)
    signed = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get(
        "X-Amz-SignedHeaders", [""]
    )
    check("Content-Length is in the signature", "content-length" in signed[0], signed[0])

    response = send(url, "PUT", headers, BODY)
    check("exact PUT accepted", response.status == 200, response.status)
    stored = api.get_object(Bucket=bucket, Key=incoming)["Body"].read()
    check("stored body is intact", stored == BODY, len(stored))

    response = send(presign(signer, bucket, f"incoming/{run}-big"), "PUT", headers, BODY + b"x")
    check("larger body refused", response.status not in (200, 201), response.status)
    response = send(presign(signer, bucket, f"incoming/{run}-small"), "PUT", headers, BODY[:-1])
    check("smaller body refused", response.status not in (200, 201), response.status)
    response = send(
        presign(signer, bucket, f"incoming/{run}-type"), "PUT", {"Content-Type": "text/plain"}, BODY
    )
    check("wrong content type refused", response.status not in (200, 201), response.status)
    expiring = presign(signer, bucket, f"incoming/{run}-late", expires=1)
    time.sleep(3)
    response = send(expiring, "PUT", headers, BODY)
    check("expired URL refused", response.status not in (200, 201), response.status)

    api.put_bucket_cors(
        Bucket=bucket,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": [ALLOWED_ORIGIN],
                    "AllowedMethods": ["PUT"],
                    "AllowedHeaders": ["content-type"],
                    "MaxAgeSeconds": 600,
                }
            ]
        },
    )
    preflight = {
        "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "content-type",
    }
    target = presign(signer, bucket, f"incoming/{run}-cors")
    response = send(target, "OPTIONS", {"Origin": ALLOWED_ORIGIN, **preflight})
    allowed = response.headers.get("access-control-allow-origin")
    check("CORS allows the site", response.status < 300 and allowed == ALLOWED_ORIGIN, allowed)
    response = send(target, "OPTIONS", {"Origin": OTHER_ORIGIN, **preflight})
    other = response.headers.get("access-control-allow-origin")
    check("CORS refuses another site", other not in (OTHER_ORIGIN, "*"), other)

    api.copy_object(Bucket=bucket, Key=raw, CopySource={"Bucket": bucket, "Key": incoming})
    size = api.head_object(Bucket=bucket, Key=raw)["ContentLength"]
    check("copy to raw/ keeps the size", size == len(BODY), size)
    listed = api.list_objects_v2(Bucket=bucket, Prefix=f"incoming/{run}").get("Contents", [])
    leftovers = sorted(item["Key"].removeprefix(f"incoming/{run}") for item in listed)
    check("refused uploads left no object", leftovers == [""], leftovers)
    for item in listed:
        api.delete_object(Bucket=bucket, Key=item["Key"])
    api.delete_object(Bucket=bucket, Key=raw)

    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}  [{detail}]")
    failed = sum(not passed for _, passed, _ in results)
    print(f"{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
