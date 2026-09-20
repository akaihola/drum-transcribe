#!/usr/bin/env bash
# Keep-alive GPU session on a Vast.ai spot instance: rent once, run any
# number of jobs over ssh, destroy on stop.
#
#   deploy/gpu-session.sh start [IDLE_MINUTES]   rent + wait for ssh (default 30)
#   deploy/gpu-session.sh run <SOURCE_URL> <SONG> <VERSION> [VARIANTS]
#   deploy/gpu-session.sh status                 print instance id if alive
#   deploy/gpu-session.sh stop                   destroy the instance
#
# Instance id lives in .gpu-instance (gitignored). Safety net: the
# instance runs a watchdog that destroys the instance itself — via the
# Vast-injected per-instance CONTAINER_API_KEY, which can only manage
# that one instance — after IDLE_MINUTES without job activity, so a
# crashed or disconnected laptop can't leave it billing forever.
# deploy/vast-worker.sh is streamed from the repo over ssh (no image
# rebuild for worker changes); it touches /tmp/alive to feed the
# watchdog. Needs .secrets.worker-s3.json and a configured vastai key.
set -euo pipefail
cd "$(dirname "$0")/.."
IMAGE=ghcr.io/akaihola/drum-transcribe-gpu:latest
STATE=.gpu-instance

# laptop: tools via uv; cloud container: vastai + boto3 installed directly
if command -v uv >/dev/null; then
    vast() { uv run vastai "$@"; }
    PYB=(uv run --with boto3 python)
else
    vast() { vastai "$@"; }
    PYB=(python3)
fi
s3() { python3 -c "import json;print(json.load(open('.secrets.worker-s3.json'))['$1'])"; }
alive() { [ -e $STATE ] && vast show instance "$(cat $STATE)" --raw 2>/dev/null | grep -q '"actual_status"'; }
ssh_cmd() {  # run "$@" on the session instance
    local hostport
    hostport=$(vast ssh-url "$(cat $STATE)") && hostport=${hostport#ssh://root@}
    ssh -F /dev/null -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o LogLevel=ERROR -o ConnectTimeout=10 \
        -p "${hostport##*:}" "root@${hostport%%:*}" "$@"
}

case ${1:?usage: gpu-session.sh start|run|status|stop} in

start)
    IDLE_MIN=${2:-30}
    if alive; then echo "session already running: instance $(cat $STATE)"; exit 0; fi
    rm -f $STATE

    echo "== searching spot offers =="
    OFFER=$(vast search offers \
        'gpu_name=RTX_3090 num_gpus=1 reliability>0.98 inet_down>500 rentable=true' \
        --type=bid -o 'dph_total' --raw | python3 -c "
import json,sys
o = json.load(sys.stdin)[0]
print(o['id'], round(o['min_bid']*1.15, 3))")
    read -r OFFER_ID BID <<<"$OFFER"
    echo "   offer $OFFER_ID, bid \$$BID/h"

    echo "== launching instance (idle self-destruct after $IDLE_MIN min) =="
    WATCHDOG='touch /tmp/alive; while sleep 60; do [ $(( $(date +%s) - $(stat -c %Y /tmp/alive) )) -gt '$(( IDLE_MIN * 60 ))' ] && curl -fsS -X DELETE -H "Authorization: Bearer $CONTAINER_API_KEY" "https://console.vast.ai/api/v0/instances/$CONTAINER_ID/?api_key=$CONTAINER_API_KEY"; done'
    ID=$(vast create instance "$OFFER_ID" --image "$IMAGE" --disk 40 \
        --onstart-cmd "$WATCHDOG" --bid_price "$BID" --raw \
        | python3 -c "import json,sys;print(json.load(sys.stdin)['new_contract'])")
    echo "$ID" > $STATE
# shellcheck disable=SC2064  # expand $ID now on purpose
    trap "echo '== start failed, destroying instance $ID =='; echo y | vast destroy instance $ID; rm -f $STATE" EXIT
    vast attach ssh "$ID" "$(cat ~/.ssh/id_ed25519.pub)" >/dev/null

    echo "== waiting for ssh (image pull ~1-10 min) =="
    for i in $(seq 1 60); do
        sleep 15
        ssh_cmd true 2>/dev/null && break
        [ "$i" = 60 ] && { echo "timed out waiting for ssh"; exit 1; }
    done
    trap - EXIT
    echo "== session ready: instance $ID =="
    ;;

run)
    SOURCE_URL=${2:?usage: gpu-session.sh run <SOURCE_URL> <SONG> <VERSION> [VARIANTS]}
    SONG=${3:?SONG missing} VERSION=${4:?VERSION missing} VARIANTS=${5:-"adtof mdx23c"}
    alive || { rm -f $STATE; echo "no live session (idle watchdog fired?) — deploy/gpu-session.sh start"; exit 1; }
    echo "== running $SONG/$VERSION on instance $(cat $STATE) =="
    ssh_cmd "SOURCE_URL=$(printf %q "$SOURCE_URL") SONG=$(printf %q "$SONG") \
        VERSION=$(printf %q "$VERSION") VARIANTS=$(printf %q "$VARIANTS") \
        S3_ACCESS_KEY=$(printf %q "$(s3 access_key)") \
        S3_SECRET_KEY=$(printf %q "$(s3 secret_key)") bash -s" \
        < deploy/vast-worker.sh

    echo "== syncing results from bucket =="
    "${PYB[@]}" - "$SONG/$VERSION" <<'PY'
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
    ;;

status)
    alive && { echo "instance $(cat $STATE)"; exit 0; }
    rm -f $STATE
    echo "no live session"
    exit 1
    ;;

stop)
    [ -e $STATE ] || { echo "no session"; exit 0; }
    echo "== destroying instance $(cat $STATE) =="
    echo y | vast destroy instance "$(cat $STATE)"
    rm -f $STATE
    ;;

*) echo "unknown subcommand: $1 (start|run|status|stop)"; exit 2 ;;
esac
