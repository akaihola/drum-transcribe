"""Download the results bucket to a local dir (container startup).

Audio files (~95 % of the bytes) become empty stand-ins instead; the web
app redirects requests for those to the bucket (serve.py _send_file).
"""

import os
import sys
from pathlib import Path

import boto3  # ty: ignore[unresolved-import]  # installed in the container only

from drum_transcribe.ingest import AUDIO_EXTS


def main() -> None:
    dest = Path(sys.argv[1]).resolve()
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
            if obj["Key"].startswith("sources/"):  # worker inputs, not results
                continue
            path = (dest / obj["Key"]).resolve()
            # keys are written by rented GPU hosts, so ".." is attacker input
            if not path.is_relative_to(dest):
                print(f"skipping unsafe key {obj['Key']!r}", flush=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix in AUDIO_EXTS:
                path.touch()
            else:
                s3.download_file(bucket, obj["Key"], str(path))
            n += 1
    print(f"synced {n} objects from {bucket} to {dest}", flush=True)


if __name__ == "__main__":
    main()
