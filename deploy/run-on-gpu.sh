#!/usr/bin/env bash
# One-command GPU processing of a song on a Vast.ai spot instance.
# Reuses an open gpu-session.sh session if one is alive (and leaves it
# running); otherwise rents an instance for this job and destroys it.
#
#   deploy/run-on-gpu.sh <SOURCE_URL> <SONG> <VERSION> [VARIANTS]
#
# SOURCE_URL: http(s) URL of the recording (presigned S3 URLs fine)
# Results land in output/<SONG>/<VERSION>/. Needs .secrets.worker-s3.json
# and a configured `vastai` API key. Interrupt-safe: rerun to continue
# (uploads happen per variant; stages cache on the instance while it lives).
set -euo pipefail
cd "$(dirname "$0")/.."
if ! deploy/gpu-session.sh status >/dev/null 2>&1; then
    # spot hosts can turn out broken (bad pull, dead GPU, outbid) — keep
    # trying fresh hosts; the health checks make each failure cheap
    for attempt in 1 2 3; do
        deploy/gpu-session.sh start && break
        [ "$attempt" = 3 ] && { echo "no usable GPU host after 3 attempts"; exit 1; }
    done
    trap 'deploy/gpu-session.sh stop' EXIT
fi
deploy/gpu-session.sh run "$@"
