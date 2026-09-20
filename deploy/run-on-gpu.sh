#!/bin/bash
# One-command GPU processing of a song on a Vast.ai spot instance:
# search offer -> launch -> wait for WORKER DONE -> sync results -> destroy.
#
#   deploy/run-on-gpu.sh <SOURCE_URL> <SONG> <VERSION> [VARIANTS]
#
# SOURCE_URL: http(s) URL of the recording (presigned S3 URLs fine)
# Results land in output/<SONG>/<VERSION>/. Needs .secrets.worker-s3.json
# and a configured `vastai` API key. Interrupt-safe: rerun to continue
# (stages cache server-side; a new instance is rented each run).
set -euo pipefail
cd "$(dirname "$0")/.."
SOURCE_URL=$1 SONG=$2 VERSION=$3 VARIANTS=${4:-"adtof mdx23c"}
IMAGE=ghcr.io/akaihola/drum-transcribe-gpu:latest

s3() { python3 -c "import json;print(json.load(open('.secrets.worker-s3.json'))['$1'])"; }

echo "== searching spot offers =="
OFFER=$(uv run vastai search offers \
    'gpu_name=RTX_3090 num_gpus=1 reliability>0.98 inet_down>500 rentable=true' \
    --type=bid -o 'dph_total' --raw | python3 -c "
import json,sys
o = json.load(sys.stdin)[0]
print(o['id'], round(o['min_bid']*1.15, 3))")
read -r OFFER_ID BID <<<"$OFFER"
echo "   offer $OFFER_ID, bid \$$BID/h"

echo "== launching instance =="
ID=$(uv run vastai create instance "$OFFER_ID" --image "$IMAGE" --disk 40 \
    --onstart-cmd 'bash /app/deploy/vast-worker.sh' \
    --env "-e SOURCE_URL=$SOURCE_URL -e SONG=$SONG -e VERSION=$VERSION -e VARIANTS='$VARIANTS' \
           -e S3_ACCESS_KEY=$(s3 access_key) -e S3_SECRET_KEY=$(s3 secret_key)" \
    --bid_price "$BID" --raw | python3 -c "import json,sys;print(json.load(sys.stdin)['new_contract'])")
trap 'echo "== destroying instance $ID =="; yes | uv run vastai destroy instance "$ID"' EXIT
echo "   instance $ID (image pull + processing takes ~5-15 min)"

echo "== waiting for worker =="
for i in $(seq 1 90); do
    sleep 20
    LOG=$(uv run vastai logs "$ID" --tail 200 2>/dev/null || true)
    if grep -q "WORKER DONE" <<<"$LOG"; then break; fi
    grep -qE "^== " <<<"$LOG" && echo "   $(grep -E '^== ' <<<"$LOG" | tail -1)"
    [ "$i" = 90 ] && { echo "timed out; logs:"; tail -30 <<<"$LOG"; exit 1; }
done
echo "   done on GPU"

echo "== syncing results from bucket =="
uv run --with boto3 python - "$SONG/$VERSION" <<'PY'
import json, sys, boto3
from pathlib import Path
c = json.load(open('.secrets.worker-s3.json'))
s3 = boto3.client('s3', endpoint_url=c['endpoint'], region_name=c['region'],
                  aws_access_key_id=c['access_key'], aws_secret_access_key=c['secret_key'])
for o in s3.list_objects_v2(Bucket=c['bucket'], Prefix=sys.argv[1] + '/')['Contents']:
    dst = Path('output') / o['Key']
    dst.parent.mkdir(parents=True, exist_ok=True)
    s3.download_file(c['bucket'], o['Key'], str(dst))
    print('  ', o['Key'])
PY
echo "== results in output/$SONG/$VERSION/ =="
