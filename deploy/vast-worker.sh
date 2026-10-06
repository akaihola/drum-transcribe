#!/usr/bin/env bash
# Runs on a rented GPU host as the instance's onstart command; baked into
# the drum-transcribe-gpu image. The cloud web app rents the host and sets
# the env below (src/drum_transcribe/coordinator.py). Processes one song
# version, uploads the results variant by variant, then deletes its own
# instance. Vast runs onstart again if it resumes a stopped instance:
# every step is repeatable, and the deadline is absolute, so a resume
# doesn't extend it.
#
# The host holds no bucket key: each fetch and upload uses a presigned
# link from the rental's link list, which names every file it may touch.
#
# Env, set at creation:
#   LINKS                         link to the link list: "<GET|PUT> <path> <link>"
#                                 lines, paths relative to <SONG>/<VERSION>/
#   SONG, VERSION, VARIANTS       the song version and the variants to make
#   GENERATION                    written into <variant>/done once a variant is up
#   RAW_BARS                      1 = keep the beat tracker's barlines as heard
#   CLAIM                         attempt id; this run's log is workers/<CLAIM>.log
#   DEADLINE                      unix time by which this attempt must be over
# Injected by Vast: CONTAINER_ID, CONTAINER_API_KEY (can delete this instance).
set -uo pipefail
cd /app   # .cache/ and .models/ resolve relative to CWD
export TQDM_DISABLE=1  # progress bars would bury the log

dest="output/$SONG/$VERSION"
LOG=/tmp/worker.log
links=/tmp/links
stage() { echo "== $* == $(date -u +%FT%TZ)"; }
link() { awk -v m="$1" -v p="$2" '$1 == m && $2 == p { print $3 }' "$links" 2>/dev/null; }
# connect and idle timeouts on every transfer; callers add --max-time for slow ones
fetch() { curl -sf --connect-timeout 10 --speed-limit 1 --speed-time 30 "$@"; }
push_log() {  # a copy: the log grows meanwhile
    cp "$LOG" "$LOG.$BASHPID"
    fetch --max-time 20 -T "$LOG.$BASHPID" "$(link PUT "workers/$CLAIM.log")" >/dev/null 2>&1
    rm -f "$LOG.$BASHPID"
}

if [ "${1:-}" != work ]; then
    exec >>"$LOG" 2>&1
    # the web app publishes the list before it rents the host
    for _ in 1 2 3; do
        fetch --max-time 30 -o "$links.part" "$LINKS" && mv "$links.part" "$links" && break
        sleep 10
    done
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
[ -s "$links" ] || { echo "could not fetch the link list"; exit 5; }
stage "checking the GPU"
# a host can look fine yet have a driver too old for the image's CUDA;
# torch then silently runs on the CPU at GPU prices
/venv/main/bin/python -c "import torch, sys; sys.exit(0 if torch.cuda.is_available() else 1)" \
    || { echo "GPU unusable on this host (driver?)"; exit 3; }

stage "waiting for the recording"
# the web app may still be fetching it; it appears under one of these names
recording() {
    for n in $(awk '$1 == "GET" && $2 ~ /^source\./ { print $2 }' "$links"); do
        fetch --max-time 20 -r 0-0 -o /dev/null "$(link GET "$n")" && { echo "$n"; return; }
    done
    return 1
}
until name=$(recording); do sleep 10; done
mkdir -p "$dest"
src="$dest/$name"

stage "fetching the recording"
# The download is the bucket speed test: a host whose route to the bucket
# crawls (2-12 kB/s on 2026-10-01) is given up before any GPU work.
if [ ! -f "$src" ]; then
    speed=$(fetch --speed-limit 200000 --speed-time 20 --max-time 600 -w '%{speed_download}' \
        -o "$src.part" "$(link GET "$name")") || { echo "bucket too slow from this host"; exit 4; }
    mv "$src.part" "$src"
    echo "   bucket speed $(( ${speed%.*} / 1000 )) kB/s"
fi

stage "restoring earlier results"
# a replacement host carries on from the beat grid and the hits found before;
# unreadable copies count as missing in the pipeline itself
for path in beats_raw.json $(printf '%s/onsets.json ' $VARIANTS); do
    if fetch --max-time 60 --create-dirs -o "$dest/$path.part" "$(link GET "$path")"; then
        mv "$dest/$path.part" "$dest/$path"
    fi
done
if [ "$RAW_BARS" = 1 ]; then touch "$dest/keep-raw-bars"; else rm -f "$dest/keep-raw-bars"; fi

for variant in $VARIANTS; do
    if [ "$(fetch --max-time 20 "$(link GET "$variant/done")")" = "$GENERATION" ]; then
        echo "   $variant: already done"
        continue
    fi
    /venv/main/bin/drum-transcribe run "$src" --variant "$variant" -o "$dest"
    stage "uploading $variant"
    # Each listed file that is here and changed since it went up: the
    # shared ones (beat grid, Opus stems) go with the first variant.
    while read -r method path url; do
        f="$dest/$path"
        [ "$method" = PUT ] && [ "$f" -nt "$f.sent" ] || continue
        case $path in *.ogg) type=audio/ogg ;; *) type=application/octet-stream ;; esac
        fetch --max-time 600 -H "Content-Type: $type" -T "$f" "$url" \
            || { echo "uploading $path failed"; exit 6; }
        touch "$f.sent"
    done < "$links"
    # last, so the marker means a complete upload of this generation
    fetch --max-time 30 -X PUT -H "Content-Type: text/plain" --data-binary "$GENERATION" \
        "$(link PUT "$variant/done")"
done
stage "all variants uploaded"
