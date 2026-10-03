#!/usr/bin/env bash
# Runs on a rented GPU host as the instance's onstart command; baked into
# the drum-transcribe-gpu image. The cloud web app rents the host and sets
# the env below (src/drum_transcribe/coordinator.py). Processes one song
# version, uploads the results variant by variant, then deletes its own
# instance. Vast runs onstart again if it resumes a stopped instance:
# every step is repeatable, and the deadline is absolute, so a resume
# doesn't extend it.
#
# Env, set at creation:
#   S3_ACCESS_KEY, S3_SECRET_KEY  worker key for the results bucket
#   SONG, VERSION, VARIANTS       results go to <SONG>/<VERSION>/ in the bucket
#   GENERATION                    written into <variant>/done once a variant is up
#   RAW_BARS                      1 = keep the beat tracker's barlines as heard
#   CLAIM                         attempt id; this run's log is workers/<CLAIM>.log
#   SOURCE                        bucket prefix where the one source.<ext> appears
#   DEADLINE                      unix time by which this attempt must be over
# Injected by Vast: CONTAINER_ID, CONTAINER_API_KEY (can delete this instance).
set -uo pipefail
cd /app   # .cache/ and .models/ resolve relative to CWD
export TQDM_DISABLE=1  # progress bars would bury the log

S3_BUCKET=${S3_BUCKET:-drum-transcribe-results}
# the worker key may touch objects only, so rclone must not check the bucket;
# contimeout/timeout catch dead connections, --max-duration slow ones
export RCLONE_CONFIG_S3_TYPE=s3 RCLONE_CONFIG_S3_PROVIDER=Scaleway \
    RCLONE_CONFIG_S3_ENDPOINT=${S3_ENDPOINT:-https://s3.fr-par.scw.cloud} \
    RCLONE_CONFIG_S3_REGION=fr-par \
    RCLONE_CONFIG_S3_ACCESS_KEY_ID=$S3_ACCESS_KEY \
    RCLONE_CONFIG_S3_SECRET_ACCESS_KEY=$S3_SECRET_KEY \
    RCLONE_S3_NO_CHECK_BUCKET=true RCLONE_CONTIMEOUT=10s RCLONE_TIMEOUT=30s
remote="s3:$S3_BUCKET/$SONG/$VERSION"
dest="output/$SONG/$VERSION"
LOG=/tmp/worker.log
stage() { echo "== $* == $(date -u +%FT%TZ)"; }
push_log() { rclone copyto --max-duration 20s "$LOG" "$remote/workers/$CLAIM.log" 2>/dev/null; }

if [ "${1:-}" != work ]; then
    exec >>"$LOG" 2>&1
    (while sleep 60; do push_log; done) &
    pusher=$!
    left=$(( DEADLINE - $(date +%s) ))
    stage "worker started on instance $CONTAINER_ID, $left s before the deadline"
    if [ "$left" -gt 0 ]; then timeout -k 30 "$left" bash "$0" work; code=$?; else code=124; fi
    [ "$code" = 124 ] && echo "deadline reached"
    stage "worker finished (exit $code), deleting this instance"
    kill "$pusher"
    push_log
    # success or not, stop the billing; Vast's instance list, not this
    # answer, is what the web app trusts to see the instance gone
    for _ in 1 2 3; do
        status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 -X DELETE \
            -H "Authorization: Bearer $CONTAINER_API_KEY" \
            "https://console.vast.ai/api/v0/instances/$CONTAINER_ID/")
        echo "self-delete: HTTP $status"
        push_log  # the last one may never finish: the DELETE stops this container
        [ "$status" = 200 ] && break
        sleep 10
    done
    exit "$code"
fi

# ---- the part bounded by DEADLINE ----
set -e
stage "checking the GPU"
# a host can look fine yet have a driver too old for the image's CUDA;
# torch then silently runs on the CPU at GPU prices
/venv/main/bin/python -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)" \
    || { echo "GPU unusable on this host (driver?)"; exit 3; }

stage "waiting for the recording"
until line=$(rclone lsf --format sp --include 'source.*' "s3:$S3_BUCKET/$SOURCE" 2>/dev/null | head -1) \
        && [ -n "$line" ]; do
    sleep 10
done
size=${line%%;*} name=${line#*;}
mkdir -p "$dest"
src="$dest/$name"

stage "fetching the recording"
# The timed download is the bucket speed test: a host whose route to the
# bucket crawls (2-12 kB/s on 2026-10-01) is given up before any GPU work.
if [ "$(stat -c %s "$src" 2>/dev/null)" != "$size" ]; then
    t0=$(date +%s)
    rclone copyto --max-duration "$(( 20 + size / 500000 ))s" "s3:$S3_BUCKET/$SOURCE$name" "$src.part" \
        && [ "$(stat -c %s "$src.part")" = "$size" ] \
        || { echo "bucket too slow from this host"; exit 4; }
    mv "$src.part" "$src"
    echo "   bucket speed $(( size / 1000 / ($(date +%s) - t0 + 1) )) kB/s"
fi

stage "restoring earlier results"
# a replacement host carries on from the beat grid and the hits found before;
# unreadable copies count as missing in the pipeline itself
rclone copy --max-duration 120s "$remote" "$dest" \
    --include "/beats_raw.json" --include "/*/onsets.json" || echo "   (restore failed, recomputing)"
if [ "$RAW_BARS" = 1 ]; then touch "$dest/keep-raw-bars"; else rm -f "$dest/keep-raw-bars"; fi

for variant in $VARIANTS; do
    if [ "$(rclone cat --max-duration 20s "$remote/$variant/done" 2>/dev/null)" = "$GENERATION" ]; then
        echo "   $variant: already done"
        continue
    fi
    /venv/main/bin/drum-transcribe run "$src" --variant "$variant" -o "$dest"
    stage "uploading $variant"
    # The shared files (recording, beat grid, Opus stems) go with every
    # variant; rclone skips what is already there. The FLACs and the kit
    # stems stay on this host. Never overwrite the web app's own files.
    rclone copy --max-duration 600s "$dest" "$remote" \
        --filter "- /keep-raw-bars" --filter "- done" --filter "- feedback.json" \
        --filter "- *.part" --filter "+ /source.*" --filter "- *.flac" \
        --filter "- /stems/mdx23c/**"
    # last, so the marker means a complete upload of this generation
    echo "$GENERATION" | rclone rcat --max-duration 30s "$remote/$variant/done"
done
stage "all variants uploaded"
