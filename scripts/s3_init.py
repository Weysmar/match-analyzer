"""Creates the development bucket and its CORS rule, waiting for the store to answer."""

import os
import sys
import time

from botocore.exceptions import BotoCoreError, ClientError
from s3_check import ALLOWED_ORIGIN, client


def main() -> int:
    bucket = os.environ["S3_BUCKET"]
    api = client(os.environ["S3_ENDPOINT"])
    deadline = time.monotonic() + 60
    while True:
        try:
            names = [item["Name"] for item in api.list_buckets().get("Buckets", [])]
            break
        except (BotoCoreError, ClientError) as error:
            if time.monotonic() > deadline:
                print(f"the S3 store does not answer: {error}", file=sys.stderr)
                return 1
            time.sleep(1)
    if bucket not in names:
        api.create_bucket(Bucket=bucket)
    api.put_bucket_cors(
        Bucket=bucket,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": [os.environ.get("SITE_URL", ALLOWED_ORIGIN)],
                    "AllowedMethods": ["PUT"],
                    "AllowedHeaders": ["content-type"],
                    "MaxAgeSeconds": 600,
                }
            ]
        },
    )
    print(f"bucket ready: {bucket}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
