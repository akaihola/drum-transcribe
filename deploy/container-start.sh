#!/bin/sh
# Cloud webapp container entrypoint: materialize credentials from env,
# sync the bucket, start the web server. Secret env vars on the container:
#   S3_ACCESS_KEY / S3_SECRET_KEY  worker bucket key (sync + presigning)
#   VAST_API_KEY                   Vast.ai API key, enables GPU processing
#   GPU_SSH_KEY_B64                base64 ed25519 private key for job ssh
set -eu
cd /app

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

if [ -n "${VAST_API_KEY:-}" ]; then
    vastai set api-key "$VAST_API_KEY" >/dev/null
fi
if [ -n "${GPU_SSH_KEY_B64:-}" ]; then
    mkdir -p ~/.ssh && chmod 700 ~/.ssh
    echo "$GPU_SSH_KEY_B64" | base64 -d > ~/.ssh/id_ed25519
    chmod 600 ~/.ssh/id_ed25519
    ssh-keygen -y -f ~/.ssh/id_ed25519 > ~/.ssh/id_ed25519.pub
fi

python sync_bucket.py /app/output
exec drum-transcribe serve /app/output --host 0.0.0.0 --port "${PORT:-8080}"
