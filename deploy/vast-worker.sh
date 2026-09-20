#!/bin/bash
# Runs inside the drum-transcribe-gpu image on a rented GPU host
# (streamed from the repo over ssh by deploy/gpu-session.sh; a copy is
# also baked into the image). Processes one song version and uploads
# results to S3-compatible storage. Touches /tmp/alive so the idle
# watchdog (see gpu-session.sh) knows a job is active.
#
# Required env (set in the Vast template / launch call):
#   S3_ACCESS_KEY, S3_SECRET_KEY   scoped worker credentials
#   SOURCE_URL                     audio to fetch (http(s) URL)
#   SONG, VERSION                  output/<SONG>/<VERSION>/
# Optional:
#   VARIANTS   default "adtof mdx23c"
#   S3_ENDPOINT default https://s3.fr-par.scw.cloud
#   S3_BUCKET   default drum-transcribe-results
set -euo pipefail
cd /app   # .cache/ and .models/ resolve relative to CWD
touch /tmp/alive

S3_ENDPOINT=${S3_ENDPOINT:-https://s3.fr-par.scw.cloud}
S3_BUCKET=${S3_BUCKET:-drum-transcribe-results}
VARIANTS=${VARIANTS:-adtof mdx23c}
dest="output/$SONG/$VERSION"

# rclone: small static binary, not baked into the image
if ! command -v rclone >/dev/null; then
    curl -fsSL https://downloads.rclone.org/rclone-current-linux-amd64.zip -o /tmp/rclone.zip
    python3 -c "import zipfile; zipfile.ZipFile('/tmp/rclone.zip').extractall('/tmp/rc')"
    install -m 755 /tmp/rc/rclone-*/rclone /usr/local/bin/rclone
fi
export RCLONE_CONFIG_S3_TYPE=s3 RCLONE_CONFIG_S3_PROVIDER=Scaleway \
    RCLONE_CONFIG_S3_ENDPOINT=$S3_ENDPOINT RCLONE_CONFIG_S3_REGION=fr-par \
    RCLONE_CONFIG_S3_ACCESS_KEY_ID=$S3_ACCESS_KEY \
    RCLONE_CONFIG_S3_SECRET_ACCESS_KEY=$S3_SECRET_KEY

mkdir -p "$dest"
urlpath=${SOURCE_URL%%\?*}   # strip query string (e.g. presigned S3 params)
src="$dest/source.${urlpath##*.}"
[ -e "$src" ] || curl -fsSL "$SOURCE_URL" -o "$src"

for variant in $VARIANTS; do
    /venv/main/bin/drum-transcribe run "$src" --variant "$variant" -o "$dest"
    # upload after each variant so an interruption loses at most one stage
    rclone copy --exclude "stems/**" "$dest" "s3:$S3_BUCKET/$SONG/$VERSION"
    touch /tmp/alive
done
echo "WORKER DONE: $SONG/$VERSION ($VARIANTS)"
