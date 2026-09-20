"""Download the whole results bucket to a local dir (container startup)."""

import os
import sys
from pathlib import Path

import boto3  # ty: ignore[unresolved-import]  # installed in the container only


def main() -> None:
    dest = Path(sys.argv[1])
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        region_name=os.environ.get("S3_REGION", "fr-par"),
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    )
    bucket = os.environ["S3_BUCKET"]
    n = 0
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            path = dest / obj["Key"]
            path.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, obj["Key"], str(path))
            n += 1
    print(f"synced {n} objects from {bucket} to {dest}", flush=True)


if __name__ == "__main__":
    main()
