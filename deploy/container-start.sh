#!/bin/sh
# Cloud webapp container entrypoint: materialize credentials from env,
# sync the bucket, start the web server. Secret env vars on the container:
#   S3_ACCESS_KEY / S3_SECRET_KEY      worker bucket key (sync, presigning,
#                                      and handed to each rented GPU host)
#   JOBS_ACCESS_KEY / JOBS_SECRET_KEY  the web app's own key: the only one
#                                      the job-record bucket admits
#   VAST_API_KEY                       Vast.ai API key; with the jobs key,
#                                      enables GPU processing (coordinator.py)
#   CREATE_PASSWORDS / TOKEN_SECRET    creation throttle (gate.py)
set -eu
cd /app
echo "container starting"  # log timestamp: splits Scaleway's start from our sync

python - <<'PY'
import json, os
json.dump({
    "endpoint": os.environ.get("S3_ENDPOINT", "https://s3.fr-par.scw.cloud"),
    "region": os.environ.get("S3_REGION", "fr-par"),
    "bucket": os.environ.get("S3_BUCKET", "drum-transcribe-results"),
    "access_key": os.environ["S3_ACCESS_KEY"],
    "secret_key": os.environ["S3_SECRET_KEY"],
}, open(".secrets.worker-s3.json", "w"))
PY

python sync_bucket.py /app/output
exec drum-transcribe serve /app/output --host 0.0.0.0 --port "${PORT:-8080}"
