---
depends_on: [16]
---
# Replace the results-bucket key

Until task [11] is deployed (task [16]), every rented GPU machine gets the
key to the `drum-transcribe-results` bucket (IAM application
`drum-transcribe-worker`). Their operators could have kept it, and it
stays valid until 2027-03-31 unless it is replaced. This task makes a new
key for the same application, moves everything that uses the key over to
it, and deletes the old one. Do it right after [16]: see the Vast.ai
incident below.

The user does the steps (they need the Scaleway login on atom). When the
user reports them done, the agent runs **Verification** below and only then
moves this task to Completed.

## Vast.ai incident (2026-10-01, reported 2026-10-10)

Vast.ai emailed on 2026-10-10: intruders got into some of its machines,
including one running our instance 53731360 (image `python:3.12-slim`)
on 2026-10-01 at 17:33 UTC. They found no sign that its contents were
read, but ask us to replace anything it could see.

- That instance was a 2026-10-01 test rental ("T2" in
  [gpu-resilience-handoff.md](../gpu-resilience-handoff.md) → Test
  results), not a song. `, vastai show audit-logs` (checked 2026-10-10):
  our account key created it from atom at 17:33:56 UTC and deleted it at
  17:33:58. Two seconds is too short to start (onstart came ≈ 57 s after
  creation in that test), so the machine got only its settings: env and
  onstart command.
- Per the T2 notes it held its own per-instance Vast key (reaches only
  that instance, gone with it), a 4000-character dummy value and two
  presigned links (expired: such links last at most 7 days).
- **Open check (agent on atom):** the T2 session is
  `c58456b0-d4fd-4d35-9da9-d51b3a6312b7` or
  `df97be52-3098-4a1f-85ed-659d322f03f3` in
  `~/.claude/projects/-home-akaihola-prg-drum-transcribe/`. Confirm that
  the create call for 53731360 passed no `S3_…`, `JOBS_…`, `VAST_API_KEY`
  or other secret value. The worker key is replaced here anyway; anything
  else found must be replaced too.
- The audit log up to its last entry (2026-10-03 13:15 UTC) shows only
  expected actions: the account key used from 88.195.128.181 (Telia home
  fiber), 85.76.x.x (Elisa mobile data, shared NAT addresses) and the web
  app's Scaleway addresses 51.159.133.236 and 151.115.146.225; rented machines deleting themselves with their own
  per-instance keys; Vast's scheduler (13.216.37.47) deleting parked
  rentals. No API keys, SSH keys or payments after the 2026-09-20 setup.
  The log records changes, not reads.
- Vast reported only this machine. But before [16], every real cloud job
  hands its machine the worker key, and any of those machines could have
  been broken into too. Hence this task.

## Before you start

- Task [16] must be **done**: GPU image `drum-transcribe-gpu:2026-10-06`
  pushed and the web app redeployed with it. Otherwise the old web app
  would hand the new key to the next rented machine as well.
- No song should be processing in the cloud right now (a running rental
  fails when its key is deleted; the web app would rent again, but why pay).
- Work on atom, in `~/prg/drum-transcribe`, in one terminal from start to
  end: later steps reuse what earlier ones remember (`$OLD`, `$APP`, …).
  Nothing below prints a secret key; access key ids (`SCW…`) are not secret.

## 1. Look up the old key

```bash
cd ~/prg/drum-transcribe
umask 077   # files made from here on are readable by you only
OLD=$(, jq -r .access_key .secrets.worker-s3.json)
, scw iam api-key get "$OLD" --profile drum-transcribe -o json > /tmp/old-key.json
APP=$(, jq -r .application_id /tmp/old-key.json)
PROJECT=$(, jq -r .default_project_id /tmp/old-key.json)
EXPIRES=$(, jq -r .expires_at /tmp/old-key.json)
, scw iam application get "$APP" --profile drum-transcribe -o json | , jq -r .name
echo "old key $OLD, project $PROJECT, expires $EXPIRES"
```

The name printed must be `drum-transcribe-worker`. If it isn't, stop and
tell the agent.

## 2. Make the new key and save it

Scaleway shows a new secret key only once, so it goes straight into the
file. The old file stays as a backup until step 7.

```bash
cp -p .secrets.worker-s3.json .secrets.worker-s3.json.old
, scw iam api-key create application-id="$APP" default-project-id="$PROJECT" \
    expires-at="$EXPIRES" description="results bucket: web app and laptop" \
    --profile drum-transcribe -o json > .secrets.new-key.json \
  && , jq --slurpfile k .secrets.new-key.json \
       '.access_key = $k[0].access_key | .secret_key = $k[0].secret_key' \
       .secrets.worker-s3.json.old > .secrets.worker-s3.json.new \
  && mv .secrets.worker-s3.json.new .secrets.worker-s3.json \
  && rm .secrets.new-key.json
NEW=$(, jq -r .access_key .secrets.worker-s3.json)
echo "old $OLD  new $NEW"
```

The two ids must differ and the new one must start with `SCW`. If any
command failed, `.secrets.worker-s3.json.old` still holds the old file:
copy it back and tell the agent.

## 3. Check that the new key works

Save a small key tester once, wait a minute (a new key needs a moment to
work everywhere), then run it:

```bash
cat > /tmp/keytest.py <<'PY'
import json, sys
import boto3
from botocore.exceptions import ClientError
c = json.load(open(sys.argv[1]))
s3 = boto3.client("s3", endpoint_url=c["endpoint"], region_name=c["region"],
                  aws_access_key_id=c["access_key"], aws_secret_access_key=c["secret_key"])
try:
    s3.list_objects_v2(Bucket=c["bucket"], MaxKeys=1)
except ClientError as e:
    sys.exit(f"{sys.argv[1]} ({c['access_key']}): refused, {e.response['Error']['Code']}")
print(f"{sys.argv[1]} ({c['access_key']}): works")
PY
uv run --no-project --with boto3 python /tmp/keytest.py .secrets.worker-s3.json
```

It must say `works`.

## 4. Give the cloud web app the new key

Updating the container's secrets **replaces all seven at once**
([operations.md](../operations.md)), so this passes every one of them,
read from their files:

```bash
set -a; . ./.secrets.throttle.env; set +a
C=9a37c1c8-6bf7-4a65-bee0-44db504fd1d3
, scw container container update "$C" region=fr-par --profile drum-transcribe \
  secret-environment-variables.0.key=S3_ACCESS_KEY \
  secret-environment-variables.0.value="$(, jq -r .access_key .secrets.worker-s3.json)" \
  secret-environment-variables.1.key=S3_SECRET_KEY \
  secret-environment-variables.1.value="$(, jq -r .secret_key .secrets.worker-s3.json)" \
  secret-environment-variables.2.key=JOBS_ACCESS_KEY \
  secret-environment-variables.2.value="$(, jq -r .access_key .secrets.jobs-s3.json)" \
  secret-environment-variables.3.key=JOBS_SECRET_KEY \
  secret-environment-variables.3.value="$(, jq -r .secret_key .secrets.jobs-s3.json)" \
  secret-environment-variables.4.key=VAST_API_KEY \
  secret-environment-variables.4.value="$(cat ~/.config/vastai/vast_api_key)" \
  secret-environment-variables.5.key=CREATE_PASSWORDS \
  secret-environment-variables.5.value="$CREATE_PASSWORDS" \
  secret-environment-variables.6.key=TOKEN_SECRET \
  secret-environment-variables.6.value="$TOKEN_SECRET" \
  > /dev/null && echo "secrets updated"
, scw container container redeploy "$C" region=fr-par --profile drum-transcribe > /dev/null \
  && echo "redeploying"
```

Repeat this until it prints `ready` (a few minutes):

```bash
, scw container container get "$C" region=fr-par --profile drum-transcribe -o json | , jq -r .status
```

Then open <https://plokkaus.vempai.men/>, open a song and play its
original recording. The audio comes from the bucket through a link the
web app signs with the new key, so if it plays, the web app has the key.

## 5. Update the other copies

- **This laptop's other tools.** List the files that still hold the old id:

  ```bash
  grep -rlsF "$OLD" ~/.config ~/.aws ~/prg/drum-transcribe/.secrets* | grep -v '\.old$'
  ```

  If `~/.config/rclone/rclone.conf` is listed (the `rclone sync` that pulls
  results), update its remote; `, rclone listremotes` names it:

  ```bash
  , rclone config update <remote-name> \
      access_key_id="$(, jq -r .access_key .secrets.worker-s3.json)" \
      secret_access_key="$(, jq -r .secret_key .secrets.worker-s3.json)"
  ```

  Run the `grep` again; it must list nothing. Tell the agent about any
  other file it lists.
- **gogo.** The agents' clone `agent@gogo:~/prg/drum-transcribe` has its
  own `.secrets.worker-s3.json`. Copy the new one over it:

  ```bash
  scp -p .secrets.worker-s3.json agent@gogo:prg/drum-transcribe/.secrets.worker-s3.json
  ```

  (or move it there the way you usually move files to gogo).
- **Password manager.** Replace the content of the
  `.secrets.worker-s3.json` note with the new file
  (`, jq . .secrets.worker-s3.json` prints it).

## 6. Delete the old key

```bash
, scw iam api-key delete "$OLD" --profile drum-transcribe && echo "old key deleted"
```

Wait a minute, then test the old key from the backup; it must say
`refused`:

```bash
uv run --no-project --with boto3 python /tmp/keytest.py .secrets.worker-s3.json.old
```

## 7. Clean up and report

```bash
rm .secrets.worker-s3.json.old /tmp/old-key.json /tmp/keytest.py
```

Tell the agent "done" and paste:

- the `old … new …` line from step 2,
- the `refused` line from step 6,
- the output of this:

  ```bash
  cd ~/prg/drum-transcribe
  NEW=$(, jq -r .access_key .secrets.worker-s3.json)
  APP=$(, scw iam api-key get "$NEW" --profile drum-transcribe -o json | , jq -r .application_id)
  echo "file holds $NEW"
  , scw iam api-key list --profile drum-transcribe -o json | , jq -r --arg a "$APP" \
    '.[] | select(.application_id == $a) | "app key \(.access_key) expires \(.expires_at) project \(.default_project_id)"'
  , scw container container get 9a37c1c8-6bf7-4a65-bee0-44db504fd1d3 region=fr-par \
    --profile drum-transcribe -o json \
    | , jq -r '"container \(.status): \([.secret_environment_variables[].key] | sort | join(" "))"'
  ls .secrets.worker-s3.json.old 2>/dev/null; echo "end"
  ```

and say whether the password manager note is updated.

## Verification (the agent, after the user reports done)

1. **Pasted output.** The old and new ids differ. Step 6 says `refused`.
   `file holds` shows the new id. There is exactly one `app key` line,
   with the new id, the old expiry and the old project. The container
   is `ready` and lists the seven secrets: `CREATE_PASSWORDS JOBS_ACCESS_KEY
   JOBS_SECRET_KEY S3_ACCESS_KEY S3_SECRET_KEY TOKEN_SECRET VAST_API_KEY`.
   Nothing is printed between that line and `end`, so the backup is gone.
2. **The live site signs with the new key.** Take a version's `source` from
   `https://plokkaus.vempai.men/api/index`. Then
   `curl -sI https://plokkaus.vempai.men<source>` must answer 302, and its
   `Location` must contain `X-Amz-Credential=<new id>%2F`. A
   `curl -s -r 0-0 -o /dev/null -w '%{http_code}' '<Location>'` on that
   link must answer 206.
3. **gogo's copy.** In `agent@gogo:~/prg/drum-transcribe`, `jq -r .access_key
   .secrets.worker-s3.json` gives the new id, and a key test like step 3's says
   `works`. Use `uv run --no-project --with boto3`, with the bucket host
   allowed. `grep -rlsF <old id> ~/prg/drum-transcribe/.secrets* ~/.config`
   lists nothing.
4. **The password manager.** The user confirmed the note is updated.
5. If the expiry or the application changed, update
   [gpu-workers.md](../gpu-workers.md) §3, [recovery.md](../recovery.md) and
   [operations.md](../operations.md) to match. If they didn't change, no
   docs need updating: they name the application and the file, not the
   key.

If all of that holds, move [15] to Completed with `[ ]`, pending the
user's acceptance. Otherwise tell the user exactly which check failed.
