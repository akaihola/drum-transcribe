# GPU processing resilience — research

Researched 2026-10-01 (three background agents, primary sources only) for
[gpu-resilience-handoff.md](gpu-resilience-handoff.md). The decisions taken
from it are in the handoff. Labels: **VERIFIED** = measured or observed
here, **DOCUMENTED** = the vendor's docs or source code say so,
**UNKNOWN** = not settled (each says what would settle it).

Several UNKNOWNs below were settled by tests the same day — CPU between
requests (A §3a: not throttled) and the Vast container key, scheduled
DELETE, `--cancel-unavail`, labels and env size (B §1, §3–5): see the
handoff's "Test results".

- [Part A — Scaleway](#part-a--scaleway): conditional writes, bucket
  policies, container runtime and billing, cron triggers, Serverless Jobs,
  queues
- [Part B — Vast.ai](#part-b--vastai): watchdog DELETE, destroyed-instance
  responses, labels, onstart limits, server-side guards, host blocklist,
  billing
- [Part C — the code](#part-c--the-code): stage caching and atomic writes,
  "variant ready", CPU offload, playback stems, the rerun path, in-process
  job state

## Part A — Scaleway

Scope: the six Scaleway questions from [gpu-resilience-handoff.md](gpu-resilience-handoff.md).
Sources: Scaleway docs (live pages, cross-checked against the
[scaleway/docs-content](https://github.com/scaleway/docs-content) repo at
commit 4e49dc6), the
[scaleway-sdk-go](https://github.com/scaleway/scaleway-sdk-go/tree/c9d8fe6301a980fd10a98a1a4eaff85b07583786)
API models, the scaleway.com pricing page, Scaleway's public product-catalog API, and
read-only measurements (boto3 against the bucket, Cockpit Loki logs, `scw … get/list`,
`scw billing consumption list`). Nothing in Scaleway was created or changed apart from
the probe objects in §1, which were deleted. No versions or delete markers were left behind.

Labels: **VERIFIED** = measured here. **DOCUMENTED** = primary docs say so.
**UNKNOWN** = not established. Each UNKNOWN says what would settle it.

### 1. Object Storage conditional writes

Yes. PutObject honours `If-None-Match: *` (create-only) and `If-Match: <etag>`
(compare-and-set). A failed precondition returns **412 PreconditionFailed** and
leaves the object unchanged. CopyObject and DeleteObject honour `If-Match` too.
In a race of 8 concurrent writers, exactly one won.

- DOCUMENTED: `If-None-Match: *` on put-object, copy-object and
  complete-multipart-upload. `If-Match: <ETag>` on the same three. If-Match needs
  `s3:PutObject` + `s3:GetObject`. A bucket policy can *enforce* conditional writes
  via the `s3:if-none-match` / `s3:if-match` condition keys. Under such a policy,
  CopyObject fails (403 without a header, 501 with one). Page posted 2026-07-03.
  https://www.scaleway.com/en/docs/object-storage/api-cli/using-conditional-writes/
  (AWS semantics it mirrors: https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)
- VERIFIED: boto3 1.43.106, worker key, prefix `sources/_cas-probe-4ae90087/` and
  `sources/_cas-probe-985d1abc/`. Run as `uv run --with boto3 python3 cas_probe.py`.
  Output excerpt:

  | request | result |
  |---|---|
  | PUT new key, `If-None-Match: *` | 200 |
  | PUT existing key, `If-None-Match: *` | **412** PreconditionFailed, content unchanged |
  | PUT, `If-Match: <wrong etag>` | **412**, unchanged |
  | PUT, `If-Match: <current etag>` | 200, new content |
  | PUT, `If-Match: <stale etag>` (after the CAS above) | **412**, unchanged |
  | PUT absent key, `If-Match: <etag>` | 404 NoSuchKey |
  | PUT absent key, `If-Match: *` | 405 NotImplemented |
  | PUT, `If-None-Match: <etag>` (not `*`) | 405 NotImplemented |
  | boto3 native `IfNoneMatch='*'` param | 412 (same as raw header) |
  | 8 threads, `If-None-Match: *` on one fresh key | 1×200, 7×412 |
  | 8 threads, `If-Match: <same etag>` | 1×200, 7×412 |
  | CopyObject to new key, `If-None-Match: *` | 200; to existing key → 412 |
  | CopyObject, `If-Match: <wrong>` | 412 |
  | CopyObject, `x-amz-copy-source-if-match: <wrong>` | 412 |
  | DeleteObject, `If-Match: <wrong>` | **412**, object kept |
  | DeleteObject, `If-Match: <current>` | 204, deleted |

  No 409 ConditionalRequestConflict was seen; losers got 412.
  Bucket versioning is `Suspended`. No bucket policy exists
  (`get_bucket_policy` → 404 NoSuchBucketPolicy).

### 2. Bucket policies: worker writes everywhere except `jobs/*`

Not expressible for the current key layout. Policies are **Allow-only** ("Deny
statements are useless"), and there is no `NotResource` and no object-key condition
key. A policy can grant writes only on listed prefixes (`<bucket>/<prefix>/*`). Results
live under open-ended top-level `<song>/` prefixes, so "everything but `jobs/`"
cannot be listed. Workable shapes: a separate bucket for job records, or a common
prefix for results.

- DOCUMENTED: version `2023-04-17` is current, and `2012-10-17` is deprecated. "only actions
  explicitly allowed by the bucket policy are permitted, if the principal is also
  allowed by an IAM policy. Deny statements are therefore useless."
  https://www.scaleway.com/en/docs/object-storage/api-cli/bucket-policy/
- DOCUMENTED: principal syntax is `"Principal": {"SCW": "application_id:<ID>"}`,
  `{"SCW": "user_id:<ID>"}`, a list of those, or `"*"`. It is not `SCW:application/...`.
  Resource is `<bucket>`, `<bucket>/*` or `<bucket>/<prefix>/*`. Condition operators are
  Bool, (Not)IpAddress, String(Not)Equals(IgnoreCase), String(Not)Like and Date*.
  Condition keys are `aws:SourceIp`, `aws:Referer`, `aws:CurrentTime`, `aws:EpochTime`,
  `aws:SecureTransport` and `s3:prefix` (ListBucket only). The conditional-writes page
  adds `s3:if-match`/`s3:if-none-match` with a `Null` operator, which is missing from the
  operator list. Same URL as above.
- DOCUMENTED, lock-out gotcha: "once you configure a bucket policy to restrict access to
  any principal, all other principals that need to keep access must now explicitly be
  granted access via the bucket policy". You lose access "if you are not the owner of the
  Organization, and if you are not explicitly allowed by the bucket policy". The owner can
  always put/delete the policy. Pushing a policy overwrites the previous one.
  https://www.scaleway.com/en/docs/object-storage/api-cli/combining-iam-and-object-storage/ ,
  https://www.scaleway.com/en/docs/object-storage/troubleshooting/lost-bucket-access-bucket-policy/
  → Any policy must also list the user's own `user_id` (console, laptop rclone) and
  every key that reads the bucket.
- VERIFIED: the container uses the **worker key** too (operations.md). An app
  `drum-transcribe-worker` (0860da9e-…) holds policy `drum-transcribe-worker-s3` with
  rule `ObjectStorageFullAccess` on project `dallape` (3bb36115-…). Checked with
  `scw iam policy list` and `scw iam rule list policy-id=7822e38a-…`. A
  "container-only" bucket or prefix therefore needs a second IAM application for
  the container.
- DOCUMENTED: `ObjectStorageFullAccess` covers PutBucketCors, PutBucketVersioning,
  PutLifecycleConfiguration and PutBucketAcl, but not bucket-policy operations (separate
  set `ObjectStorageBucketPolicyFullAccess`).
  https://www.scaleway.com/en/docs/object-storage/reference-content/s3-iam-permissions-equivalence/
  → A rented host can today change the bucket's CORS or add a lifecycle rule that
  expires every object. The sets `ObjectStorageObjectsRead/Write/Delete` exist and would
  be enough for a worker.
- UNKNOWN: whether wildcards mid-resource (`<bucket>/*/x/*`) work. The docs only show
  trailing `/*`. A test policy on a scratch bucket would settle it.

### 3. Serverless Containers runtime model

(a) "CPU only while a request is in flight" is **not documented** anywhere.
(b) Scale-to-zero comes **15 min** after the last request (documented). Measured:
between 15.4 and 17.2 min.
(c) Billing is **per second of instance uptime**, idle tail included, not per
request. The rates are €0.00001/vCPU-s and €0.000002/GB-s. The free tier is
200 000 vCPU-s and 400 000 GB-s per account per month. Always-on at 1 GB / 0.5 vCPU
costs ≈ **€18.1/month gross**, or **€15.3** after the full free tier.

- (a) UNKNOWN. No statement on CPU allocation outside requests exists in the
  container docs, FAQ, limitations, sandbox or concurrency pages (grep of docs-content
  for throttl/background/idle/CPU). Indirect evidence that background work is not frozen:
  the handoff timeline has the container's job thread creating the third rental at 12:17.
  That was 12.5 min after the last request (12:04:52, see (d)). To settle it: a probe endpoint
  starts a thread that logs a busy-loop counter every 10 s. Call it once, then compare
  the rates during and after the request in Cockpit.
- (b) DOCUMENTED: "If you set a value of `0`, all instances … will be terminated after 15
  minutes of inactivity". Scale-down to 1 happens after 30 s. "Time before scale to zero:
  15 minutes".
  https://www.scaleway.com/en/docs/serverless-containers/reference-content/containers-autoscaling/ ,
  https://www.scaleway.com/en/docs/serverless-containers/reference-content/containers-limitations/
- (b) DOCUMENTED: the request timeout can be set from 10 s to **60 min**. The container is
  configured at 300 s (`scw container container get 9a37c1c8-…` → `timeout = 300s`,
  `min_scale 0`, `max_scale 1`, `mvcpu_limit 500`, `memory_limit_bytes 1000000000`,
  `sandbox v2`). Same limitations URL.
- (c) DOCUMENTED: consumption is "the memory tier chosen by the container run duration",
  and the same for vCPU. Free-tier example: 400 000 GB-s and 200 000 vCPU-s.
  https://www.scaleway.com/en/docs/serverless-containers/faq/#how-am-i-billed-for-serverless-containers .
  Current prices: Memory €0.000002/GB-s after 400 000 GB-s, vCPU €0.00001/vCPU-s after
  200 000 vCPU-s, "Free Tier per account and per month".
  https://www.scaleway.com/en/pricing/serverless/ . The same values are in the catalog API
  (`/paas/caas/cpu_consumption/fr-par` 0.00001 €/vCPU-s,
  `/paas/caas/memory_consumption/fr-par` 0.000002 €/GB-s):
  https://api.scaleway.com/product-catalog/v2alpha1/public-catalog/products
- (c) VERIFIED (inferred from billing): `scw billing consumption list billing-period=2026-10`
  reports **9 631 vCPU-s** and **17 721 GB-s** for project dallape on 2026-10-01. That
  project holds `webapp` and the unrelated `app` container (560 mvCPU, 1 GB). Modelled
  from Cockpit instance lifetimes (first to last log line per instance, both containers,
  19 instances seen 2026-09-30 22:00 → 10-01 17:00 UTC, clipped to October):

  | assumed billing | vCPU-s | GB-s |
  |---|---|---|
  | request-active spans only | 3 667 | 7 121 |
  | spans + 10 min idle tail | 9 427 | 17 921 |
  | spans + 15 min idle tail | 12 307 | 23 321 |

  The billed amount is 2.6× what the active spans explain. It matches instance uptime
  including the idle tail, with the last hours probably not yet reported.
  Consequence: every cold wake-up costs about 16–17 min of instance time
  (~500 vCPU-s + ~1 000 GB-s ≈ €0.007 gross), even if it serves a single request.
- (c) Always-on cost, min_scale 1, 1 GB / 500 mvCPU, 30-day month (2 592 000 s):
  vCPU 1 296 000 vCPU-s = €12.96. Memory 2 592 000 GB-s = €5.18. **Gross €18.14**.
  Minus the full free tier (€2.00 + €0.80): **€15.34**. A 730 h month gives €18.40 / €15.60.
  Hourly: €0.025.
- (c) VERIFIED (usage; "per account" is DOCUMENTED): the free tier is already mostly used. September 2026 billed
  177 102 vCPU-s and 330 610 GB-s of Serverless Containers across projects dallape and
  "AI app prototypes", against 200 000 / 400 000 free. The free tier covers ~111
  instance-hours/month of a 0.5 vCPU / 1 GB container, shared with `app` and `carl`.
- (d) VERIFIED: Cockpit Loki,
  `query={resource_type="serverless_container", resource_name="drumtranscribe1eb07827-webapp"}`,
  2026-09-24 16:38 → 2026-10-01 16:50 UTC (14 283 lines; retention reaches back ~7 days).
  Each instance has its own `resource_instance` pod name.
  - No log line marks a stop. The app prints nothing on SIGTERM, and Scaleway emits no
    platform line to Cockpit. So the stop time can only be bracketed.
  - Longest idle gap an instance **survived** (next request served by the same pod):
    15.4 min (09-25 17:19:55 → 17:35:19). Others: 15.3, 15.3, 14.9, 14.9 min.
  - Shortest idle gap followed by a **new pod** (not a redeploy, i.e. same revision number):
    17.2 min (09-25 18:02:00 → 18:19:12 `container starting`). Then 17.6, 18.0, 18.9 min.
  - ⇒ scale-to-zero happens **15.4–17.2 min after the last request**, consistent with the
    documented 15 min.
  - 2026-10-01: pod `…8flkp` started 11:59:57, and its last request was 12:04:52 (a
    `/api/seek` poll). There were no lines after that. The next pod (`…f4rbg`) started at 12:33:39.
    By the bracket, `…8flkp` was gone between 12:20:17 and 12:22:04.
  - Cold start, `container starting` → first request served (66 starts with a request
    within 100 s; includes redeploys): median
    18.9 s, p90 32.5 s, max 61.6 s. `container starting` → sync done: median 16.8 s.
  - 10 of 77 starts served no request at all (e.g. 09-26 13:26:08, 14:38:42). Each still
    costs a full idle tail.

### 4. Container cron triggers

A cron trigger sends one HTTP request to the container on schedule. Method
(get/post/put/patch/delete; the console also lists OPTIONS), **path** (e.g.
`/api/reconcile`), **body** and **headers** are configurable. Triggers can be created,
updated and deleted through the API at runtime. The smallest documented permission
is **`ContainersFullAccess` on the whole project**. Triggers have no price of their
own. You pay for the container time each call causes.

- DOCUMENTED: in API v1 cron is a trigger type with "Custom HTTP paths and headers" and
  "Select HTTP method" (`GET`, `POST`, `PUT`, `DELETE`, `PATCH`, `OPTIONS`; console default
  POST). "The arguments of a CRON trigger are injected in the body of the HTTP request".
  https://www.scaleway.com/en/docs/serverless-containers/reference-content/v1-migration-guide/ ,
  https://www.scaleway.com/en/docs/serverless-containers/how-to/add-trigger-to-a-container/
- DOCUMENTED (API model): `CreateTriggerRequest{container_id, name, destination_config
  {http_path, http_method}, cron_config{schedule, timezone, body, headers}}`. Endpoints:
  `POST/GET/PATCH/DELETE /containers/v1/regions/{region}/triggers[/{id}]`. There is no
  enable/disable flag, so pausing means deleting the trigger or changing its schedule.
  [container_sdk.go](https://github.com/scaleway/scaleway-sdk-go/blob/c9d8fe6301a980fd10a98a1a4eaff85b07583786/api/container/v1/container_sdk.go)
  (structs `CreateTriggerRequest`, `TriggerCronConfig`, `TriggerDestinationConfig`,
  `UpdateTriggerRequest`). The CLI matches: `scw container trigger create --help` (v2.60.0)
  lists `destination-config.http-path`, `destination-config.http-method`,
  `cron-config.{schedule,timezone,body,headers.{key}}`.
- DOCUMENTED: schedules are unix-cron with every-minute granularity. The docs contradict
  each other on time zones: the reference says UTC, not changeable; the how-to and the API
  have a timezone field.
  https://www.scaleway.com/en/docs/serverless-containers/reference-content/cron-schedules/
- DOCUMENTED: Scaleway injects `X-Forwarded-For`, `X-Forwarded-Proto` and `X-Request-ID`
  into every request. There is no documented header that marks a trigger call, so put a secret in
  `cron-config.headers` and check it in `/api/reconcile`. The endpoint is public.
  https://www.scaleway.com/en/docs/serverless-containers/reference-content/request-headers/
- UNKNOWN: whether the trigger's caller waits for the whole response up to the container
  `timeout` (300 s now, max 60 min), and whether CPU is full during that request (see
  §3a). To settle it: one cron trigger on a test path that sleeps/computes for 240 s,
  logging its start and end.
- DOCUMENTED: permission sets for Containers are only `ContainersReadOnly`,
  `ContainersFullAccess` and `ContainersPrivateAccess`, all project-scoped. Containers are not among
  the products that support resource-level IAM conditions (only IAM, Key Manager and
  Secret Manager are). Request-level conditions (`request.ip`, `request.time`,
  `request.user_agent`) exist, but the container has no fixed egress IP.
  https://www.scaleway.com/en/docs/iam/policies-permissions/permission-sets/ ,
  https://www.scaleway.com/en/docs/iam/policies-permissions/supported-products-resource-level/
  VERIFIED via `scw iam permission-set list`: no finer container set exists.
  Project dallape also holds container `app` (namespace dallape), so such a key could
  modify, redeploy or delete that too, and change webapp's own env/secrets.
- VERIFIED: no triggers exist today (`scw container trigger list` → empty).
- DOCUMENTED (by absence): the pricing page and the product catalog have no trigger SKU.
  The FAQ suggests cron triggers "to keep your containers active … without having to
  provision a minimum of 1 vCPU". https://www.scaleway.com/en/docs/serverless-containers/faq/
  With §3c: a schedule every ≤15 min keeps the container permanently up (€0.025/h gross).
  An hourly schedule means ~24 cold starts × ~16.5 min ≈ 6.6 h/day ≈ €5/month gross.

### 5. Serverless Jobs

Fits a run-to-completion orchestrator. Runs last up to **24 h** and can be started on
demand through the API with per-run env vars and arguments. Jobs support cron triggers,
0–5 automatic retries, and images from the private `drum-transcribe` registry namespace.
Prices equal Containers' prices, and Jobs have their own free-tier line. Two unknowns
remain: start latency, and the API's maturity (v1alpha2).

- DOCUMENTED: timeout 24 h per job run, max 6 vCPU / 16 GB, 10 GB ephemeral storage,
  400 parallel runs per org. Defaults are 1120 mvCPU / 2048 MB. The image must be linux/amd64.
  `/tmp` is in memory (gVisor).
  https://www.scaleway.com/en/docs/serverless-jobs/reference-content/jobs-limitations/
- DOCUMENTED: billing multiplies the tier by the job run duration. The pricing page lists, for Jobs
  separately: €0.000002/GB-s after 400 000 GB-s and €0.00001/vCPU-s after 200 000 vCPU-s,
  "Free Tier per account and per month". The invoice line is "Serverless Jobs - CPU Pack".
  https://www.scaleway.com/en/pricing/serverless/ , https://www.scaleway.com/en/docs/serverless-jobs/faq/
  A 60-min run at 0.5 vCPU / 1 GB costs €0.025 gross. The free tier covers ~111 such hours a month.
- DOCUMENTED: `POST /serverless-jobs/v1alpha2/regions/{region}/job-definitions/{id}/start`
  takes `startup_command`, `args`, `environment_variables` and `replicas` for that run, so the
  song/version can be passed per run. Runs can be stopped via `…/job-runs/{id}/stop`.
  [jobs_sdk.go](https://github.com/scaleway/scaleway-sdk-go/blob/c9d8fe6301a980fd10a98a1a4eaff85b07583786/api/jobs/v1alpha2/jobs_sdk.go)
  (`StartJobDefinitionRequest`). Console equivalent: "Run job with options",
  https://www.scaleway.com/en/docs/serverless-jobs/how-to/run-job/
- DOCUMENTED: the permission is `ServerlessJobsFullAccess` (project-scoped; the only other set is
  ReadOnly). It "does not include permissions for Container Registry and Secret Manager".
  https://www.scaleway.com/en/docs/iam/policies-permissions/permission-sets/ . A key that
  can start jobs can also create job definitions with any image in the project.
- DOCUMENTED: cron triggers, several per job definition, with time zone and per-trigger
  command/args override.
  https://www.scaleway.com/en/docs/serverless-jobs/how-to/manage-job-triggers/
- DOCUMENTED: retries 0–5. A retry happens on `failed` with an exit code. There is no
  retry on infrastructure failures (null exit code) or on `interrupted`.
  https://www.scaleway.com/en/docs/serverless-jobs/how-to/manage-job-retries/
- DOCUMENTED: jobs can use images from Scaleway Container Registry (or public external
  registries; "Private external container registries are currently not supported").
  https://www.scaleway.com/en/docs/serverless-jobs/how-to/create-job/ . VERIFIED: the
  namespace `drum-transcribe` (b898a716-…) is private and lives in project dallape
  (`scw registry namespace list project-id=3bb36115-…`). The webapp image already
  contains `vastai`, ssh and boto3, so a job could reuse it with a different
  startup command.
- UNKNOWN: start latency. The docs only give the states `initialized → validated → queued →
  running`, where `queued` = "waiting for compute resources".
  https://www.scaleway.com/en/docs/serverless-jobs/concepts/ . There is no job history to
  measure (`scw jobs run list` → empty). To settle it: one test run of the webapp image
  with `startup_command ["true"]`, timing `created_at → started_at → terminated_at`.
- Fit: runs that live 20–60 min fit easily within 24 h. Starting a run per song from
  `/api/create` and retrying on failure match the "rent, wait, retry" loop. A Job gives
  no "one run per song" guarantee, so the bucket lease (§1) is still needed. The
  orchestrator no longer depends on the container's 15-min idle life or on any
  per-request CPU behaviour.

### 6. Scaleway Queues and NATS triggers for delayed wake-ups

No. Scaleway Queues supports **neither per-message nor per-queue `DelaySeconds`**.
`ChangeMessageVisibility` accepts only `0` or the queue's own timeout. So the idea "enqueue a
delayed reconcile message" cannot be built. NATS docs describe no delayed delivery either.

- DOCUMENTED: SendMessage `DelaySeconds`: **N**. SendMessageBatch: DelaySeconds is not
  supported. The queue attribute `DelaySeconds` is **N**, and so is
  `ApproximateNumberOfMessagesDelayed`. ChangeMessageVisibility `VisibilityTimeout`: "Only '0'
  and the current queue visibility timeout are supported". `VisibilityTimeout` and
  `MessageRetentionPeriod` (queue attributes) are supported.
  https://www.scaleway.com/en/docs/queues/reference-content/queues-support/
- DOCUMENTED: a queue trigger has at most 10 in-flight requests and uses back-pressure. It retries up to 3
  times if the container returns ≥300. The retry timing is not documented.
  https://www.scaleway.com/en/docs/serverless-containers/reference-content/configure-trigger-inputs/ ,
  https://www.scaleway.com/en/docs/serverless-containers/how-to/add-trigger-to-a-container/
  Adding a queue or NATS trigger needs `MessagingAndQueuingReadOnly` plus your own queue
  credentials (since API v1).
- UNKNOWN: whether a "return 5xx to re-deliver after the visibility timeout" trick
  would give a delayed retry. The timing is undocumented and capped at 3 retries, so it
  is not worth a test.
- DOCUMENTED: NATS includes JetStream. No scheduling or delay feature is mentioned.
  https://www.scaleway.com/en/docs/nats/concepts/
- DOCUMENTED: pricing is by volume. SQS €0.01/GB and NATS €0.01/GB volume
  (+ €0.0002/GB storage) per the catalog API (`/paas/messaging/sqs/volume/fr-par`).
  https://www.scaleway.com/en/docs/queues/faq/ (billing "based on queue volume"). No free tier
  was found. VERIFIED: SQS is `disabled` in project dallape
  (`scw mnq sqs get-info project-id=3bb36115-…`).

### Implications for the design

- **Use the bucket for a CAS lease.** Create with `If-None-Match: *`, renew and hand over with
  `If-Match`, release with `DELETE If-Match`. It is atomic under concurrency (§1). CAS stops
  races between honest writers. It does **not** stop a rented host, which holds the same key
  and can read the ETag. The reconciler must still treat lease/job contents as untrusted.
- **Protect the job records with a separate bucket, not a prefix.** Use a new bucket (e.g.
  `drum-transcribe-jobs`) whose policy allows only a new container-only IAM application
  plus the user's `user_id`. The worker key's project-wide IAM grant is then blocked by
  the policy. This needs a second S3 key in the container, since it currently runs on the
  worker key.
- **Narrow the worker key** from `ObjectStorageFullAccess` to the objects sets. Today a host
  can change CORS, versioning or lifecycle on the results bucket.
- After the page closes, the container lives **15–17 min** at most, and whether it gets CPU
  is undocumented. Nothing long-running belongs in it without a wake-up source.
- **Cron trigger as the wake-up.** It can call `POST /api/reconcile` with a secret header.
  While a schedule of ≤15 min exists, the container never sleeps (~€0.025/h). Toggling the
  trigger from the app needs a `ContainersFullAccess` key on project dallape, which also
  holds the `app` container. A dedicated Scaleway project for drum-transcribe would contain
  that risk.
- **Serverless Jobs is the cleanest orchestrator.** It runs to completion (≤24 h), is started
  per song via API with env vars, has built-in retries, and costs about the same per hour.
  Costs: a `ServerlessJobsFullAccess` key in the container (project-wide), an alpha API, and
  an unmeasured start latency.
- **Drop Queues/NATS delayed messages.** They are not supported.
- **The free tier is mostly spent** by existing containers (Sept: 177k/200k vCPU-s). Budget at
  gross prices.
- **Cheap tests still open:** (1) CPU between requests (§3a probe); (2) whether a cron
  request is held for the full timeout (§4); (3) Jobs start latency (§5). Each needs a
  create/deploy step, so none were run here.

## Part B — Vast.ai

These are Vast.ai answers for [gpu-resilience-handoff.md](gpu-resilience-handoff.md):
F2, F3, F7, F9, labels, onstart, the host blocklist and billing. Sources are
the `vastai` CLI 1.7.0 source in `.venv/lib/python3.11/site-packages/`, which is
the same as GitHub master for destroy, start, stop and show (PyPI latest is
1.8.2), plus docs.vast.ai and read-only calls against our account. CLI paths
below are relative to `site-packages/`.

Labels: **VERIFIED** means observed here. **DOCUMENTED** means the primary docs
or the CLI source say so. **UNKNOWN** means not settled, and the entry says
what would settle it.

### 1. F7: does the watchdog's `DELETE` destroy or only stop?

It destroys: the watchdog sends the same `DELETE /api/v0/instances/<id>/` as
`vastai destroy instance`, while stop is a `PUT` to the same URL. The account
audit log shows **no API call at all** from the 2026-10-01 instance's container
key. Vast stopped the instance on its own side, during or just after the
window in which the watchdog was due. Why the watchdog stayed silent is UNKNOWN.

Evidence:

- DOCUMENTED: CLI destroy is `client.delete(f"/instances/{id}/")`
  (`vastai/api/instances.py:309-317`). Stop is `client.put(f"/instances/{id}/",
  {"state": "stopped"})` (`:331-339`). The base URL is
  `https://console.vast.ai/api/v0`, sent with `Authorization: Bearer <key>`
  (`vastai/api/client.py:24,56-86,160-164`). The watchdog's curl
  (`deploy/gpu-session.sh:81`) uses the same method and URL; its `?api_key=`
  query parameter is redundant. The API reference says "Destroys/deletes an
  instance permanently"
  (https://docs.vast.ai/api-reference/instances/destroy-instance), and
  state changes are a PUT
  (https://docs.vast.ai/api-reference/instances/manage-instance).
- VERIFIED, from the 2026-09-20 watchdog test (Claude session log
  `b6c21327…`). Instance 51789560 ran with a 6 min idle timeout after the
  laptop script was killed. `vastai show audit-logs --raw` has
  `api.instance_DELETE` at 18:15:54 UTC from the host's IP (85.51.34.67)
  under its own `api_key_id` 28802499. At 18:15:56, `show instance` returned
  `{"instances": null}` and `show instances` returned `[]`.
- VERIFIED: another container-key DELETE happened on 2026-09-22 19:45:14
  (instance 52105903, host 194.228.55.129, `api_key_id` 29115808), so
  container-key calls are audit-logged under their own key id. Whether that
  instance ended destroyed or stopped was not recorded.
- CONTAINER_API_KEY scope, DOCUMENTED: "Per-instance API key for CLI commands
  from inside the container". The examples run `show`/`start`/`stop`/`destroy
  instance $CONTAINER_ID`
  (https://docs.vast.ai/guides/instances/docker-environment, sections
  "Predefined Variables" and "Using the CLI from Inside an Instance"). The same
  page rebuilds a lost key as
  `md5(~/.ssh/authorized_keys) + md5($VAST_CONTAINERLABEL)`, and the host can
  see both inputs. The CLI calls it "the instance-level API key that has
  permissions to fetch deployment blobs"
  (`vastai/serverless/remote/serve_deployment.py:25-26`). UNKNOWN: whether it
  can reach other instances or account data. The claim "only that one
  instance" in gpu-workers.md is not documented. To settle it, call
  `GET /api/v0/instances/` and `GET /api/v0/users/current/` with the container
  key on a rented instance and record the status codes.

Forensics for instance 53710757 on host 92.97.193.95. Sources: `vastai show
audit-logs --raw`, `vastai show invoices-v1 --charges -s 2026-10-01 -e
2026-10-02 --raw`, and session log `b67fe007…`:

| UTC | event | source |
|---|---|---|
| 14:41:38 | created (`api.ask_PUT`, laptop key) | audit log |
| 14:41:59 | `running` | session log |
| 14:48:22 | last bucket upload (fused), then the worker touches `/tmp/alive` | bucket listing in session log |
| 15:18:22–15:19:22 | watchdog due (`gpu-session.sh start 30`, 60 s loop) | session log, gpu-session.sh:81 |
| ≈15:23 | end of GPU billing (0.686 h); stop was ≤ this, see §7 tail | charges |
| 15:28:43 | `actual_status=exited intended_status=stopped cur_state=stopped next_state=stopped`, `status_msg="success, running …"` | session log |
| 15:28:52 | `api.instance_DELETE`, laptop key (`gpu-session.sh stop`) | audit log |
| — | storage billed 0.787 h, i.e. until ≈15:28:50 | charges |

- VERIFIED: no key made an `api.instance_DELETE` or `api.instance_PUT` (stop)
  call on 53710757 before 15:28:52. The stop came from Vast's side.
- VERIFIED: the credit balance did not run out. Credit is still positive,
  and the only top-up was on 2026-09-20 (`show user`, audit log). A
  zero-credit stop is ruled out.
- DOCUMENTED: an interruptible instance that loses its bid "is stopped
  (killing running processes)"
  (https://docs.vast.ai/guides/reference/faq/rental-types). "When outbid, the
  instance moves to `stopped` (not destroyed) and storage charges continue"
  (`vastai/SKILL.md:158`). Stopping the container also kills the watchdog.
- UNKNOWN: why no DELETE was logged from 15:18:22 on. Billing ends up to
  ~5 min after the real event (§7), so the stop happened at ≈15:18–15:23,
  inside or right after the watchdog window. Two readings remain:
  - (a) an outbid near that time, with the watchdog failing silently. The
    watchdog's `curl -f` errors go nowhere, and the loop retries each minute.
  - (b) Vast handled the container-key DELETE as a stop without logging it.
    The 2026-09-20 test contradicts this: the same call destroyed the
    instance and was logged.

  To settle this run, look in the Vast account's mailbox for an "Instance
  outbid" or "Instance stopped" message around 15:20 UTC (the event types are
  listed at https://docs.vast.ai/guides/reference/notifications). To settle
  the question in general, repeat the 2026-09-20 test on today's image (rent
  with a 3 min idle timeout, watch `show instance` and the audit log, a few
  cents), and have the watchdog log curl's HTTP status somewhere durable.

### 2. F9: what does `show instance` return for a destroyed instance?

The API returns HTTP 200 with `{"instances": null}`; the CLI prints exactly
that with `--raw` and exits 0. Rule: an instance is gone when stdout parses as
JSON and has no `id` key. A real row with `actual_status: null` means the
instance is still provisioning, not gone.

- VERIFIED:
  `curl -H "Authorization: Bearer …" 'https://console.vast.ai/api/v0/instances/53710757/?owner=me'`
  returned `{"instances": null}` with HTTP 200. `uv run vastai show instance
  53710757 --raw` (and the same for 53709772) printed `{"instances": null}`
  and exited 0. An id that was never ours (`show instance 1`) gives the same
  answer, so null means "not ours, or no longer exists".
- DOCUMENTED: `show_instance` returns `None` when `r.json()["instances"]` is
  None (`vastai/api/instances.py:83-91`), and `--raw` then prints
  `{"instances": None}` (`vastai/cli/commands/instances.py:47-55`).
- VERIFIED, F9 as it happened: `pipeline.log` line 70 says "instance starting,
  host downloads at 0 Mbit/s". It was written after 53705226 had been
  destroyed at 14:26:18 (audit log). The wait loop's
  `d.get('actual_status') or 'starting'` (`gpu-session.sh:99-102`) turns a
  null response into "starting".

  Correction to the handoff: `alive()` (`gpu-session.sh:36`) greps for
  `"actual_status"`, which a null response lacks. So `alive()` already
  treats destroyed instances as dead. It does report stopped and exited
  instances as alive.
- VERIFIED: a live instance has a row with `actual_status` null for its
  first seconds (`pipeline.log` line 95: "starting" with inet_down 1677).
  DOCUMENTED: `null` means Provisioning (`vastai/SKILL.md:139`).
- VERIFIED: on an HTTP error the CLI writes `{"error": true, "status_code": …,
  "msg": …}` to **stderr**, writes nothing to stdout, and still exits 0.
  `show instance 53710757 --raw --api-key invalid-key-test` printed
  `{"error": true, "status_code": 404, "msg": "Invalid user key"}` and
  exited 0 (`vastai/cli/main.py:32-41,200-224`). In the current wait loop,
  the empty stdout breaks the JSON parse and triggers "instance disappeared
  (spot outbid?)". An API hiccup counts as a disappearance, and a real
  destroy does not.
- DOCUMENTED: Vast's own start-up wait (`vastai/cli/commands/machines.py:1168-1297`)
  treats these cases as follows:
  - gone: `None`, HTTP 404, or status `destroyed`, `terminated` or `offline`;
  - failed start: `stopped` or `exited` in either `intended_status` or
    `actual_status`, or a `status_msg` containing
    error/failed/exception/oci runtime/permission denied;
  - it gives up after 900 s.

  The API reference adds: "if `actual_status` becomes `exited`, `unknown`, or
  `offline` it will never reach `running`"
  (https://docs.vast.ai/api-reference/instances/show-instance).
- UNKNOWN: whether a freshly created id can briefly return null. Vast's
  self-test retries on `None` (`machines.py:1220-1224`). Our rentals always
  had a row by the first poll, 15 s after creation.

Rule for a wait loop or reconciler:

1. Empty stdout, or stderr JSON with `"error": true`, means an API problem:
   retry, and count these failures separately.
2. JSON without an `id` key (`instances` is null) means gone. Accept this
   after the row has been seen once, or after two nulls in a row.
3. `intended_status == "stopped"`, or `actual_status` in
   `exited`/`stopped`/`unknown`/`offline`, means dead for us: destroy and
   re-rent.
4. A `status_msg` containing an error token means a failed start: destroy it.
5. `actual_status` null on a real row means provisioning: keep waiting.

### 3. Labels

Labels can be set at creation (`create instance --label`) or later (`label
instance <id> <label>`). `show instance(s)` returns them, and `show instances
--label X` filters on the server by exact match. The documented maximum is
1024 characters (manage-instance); no charset rule is documented.

- DOCUMENTED: `--label` on create (`vastai/cli/commands/instances.py:128`)
  goes into the payload as `"label"` (`vastai/api/instances.py:249`).
  `label instance` sends `PUT /api/v0/instances/<id>/ {"label": …}`
  (`vastai/api/instances.py:354-357`; CLI `instances.py:462-478`).
  `vastai/SKILL.md:96` shows a `--label` flag for `label instance`, but the
  label is a positional argument.
- DOCUMENTED: the label has `maxLength: 1024`
  (https://docs.vast.ai/api-reference/instances/manage-instance). The create
  docs only say "string"
  (https://docs.vast.ai/api-reference/instances/create-instance). Charset:
  UNKNOWN. To settle, create an instance with
  `--label 'highway-star/levyversio'` and read it back.
- DOCUMENTED: `show instances --label L1 L2` sends
  `select_filters={"label": {"in": [...]}}`, with `''` matching unlabelled
  instances (`vastai/cli/commands/instances.py:969,1027-1030`). Server
  operators are `eq neq gt gte lt lte in notin`, and the response includes
  `label_counts` (https://docs.vast.ai/api-reference/instances/show-instances).
  There is no prefix or LIKE match.
- VERIFIED: `uv run vastai show instances --label 'highway-star/levyversio'
  --raw` returned `[]` with exit 0, so the filter is accepted. Rows from
  `show instances --raw` carry `label` (2026-10-01 session: `'label': None`).
- DOCUMENTED: charges can be filtered by label with `show invoices
  --instance_label`, which uses `POST /api/v0/contracts/fetch/`
  (`vastai/cli/commands/billing.py:294,314-326`). That allows per-version
  spend caps.

### 4. Onstart and env

`onstart` is limited to 4048 characters. It runs on every container start,
including when an outbid instance resumes. The 2.4 KB worker fits as is, and
shrinks to 1.7 KB with gzip+base64. Vast stores env and onstart and returns
both from `show instance`, and the host can read both. Account-level "env
vars" exist, but Vast injects them into every container, so they hide nothing
from hosts.

- DOCUMENTED: "`onstart` field is limited to 4048 characters -- gzip+base64
  for longer scripts" (Key Quirks,
  https://docs.vast.ai/api-reference/instances/create-instance;
  `vastai/SKILL.md:128`).
- VERIFIED: `deploy/vast-worker.sh` is 2437 bytes, and `gzip -9 | base64 -w0`
  makes it 1716 chars. For example, `echo <b64> | base64 -d | gunzip >
  /tmp/w.sh; …` fits alongside the ~260-char watchdog.
- UNKNOWN: the maximum `--env` length. Neither the docs nor the CLI set one.
  The CLI splits `-e K=V` tokens on spaces, keeps `=` inside values and strips
  surrounding quotes (`vastai/utils.py:148-184`), so a base64 value passes
  intact. To settle, create an instance with a ~4 KB value and read
  `extra_env` back.
- `--args` cannot carry a script in ssh mode. DOCUMENTED: "In both Jupyter
  and SSH mode, the docker entrypoint for your image will not be run"
  (https://docs.vast.ai/guides/templates/template-settings). With `--ssh`,
  the CLI sets runtype `ssh_direc ssh_proxy` even when args are given
  (`vastai/api/instances.py:110-146`).
- Onstart re-runs, DOCUMENTED: for SSH instances, "/root/onstart.sh … runs
  automatically on container startup"
  (https://docs.vast.ai/guides/reference/faq/instances). Interruptible
  instances "Resume automatically when priority returns"
  (https://docs.vast.ai/guides/instances/choosing/instance-types). We have
  not observed a resume. If one happens, the watchdog restarts and its first
  `touch /tmp/alive` resets the idle timer.
- Visibility:
  - VERIFIED: `show instance(s) --raw` returns `onstart` and `extra_env`
    word for word to the account key. The 2026-10-01 session printed the
    full watchdog and `extra_env: {'CONTAINER_RUNTIME': 'gvisor'}`.
  - DOCUMENTED: env set at creation is visible to the onstart script. Hosts
    "can technically access files on their machines", and the docs advise
    "Don't store credentials in instances"
    (https://docs.vast.ai/guides/instances/manage-instances,
    https://docs.vast.ai/guides/reference/faq/security).
  - Host access to env is not stated in so many words, but it follows from
    the host running the container. This is the same exposure as today's
    ssh stream.
- Account secrets, DOCUMENTED: "User Account Variables … automatically
  injected into every container you launch" (docker-environment page). The
  CLI manages them with `create/update/delete/show env-var`, which use
  `/api/v0/secrets/` (`vastai/api/auth.py:20-60`); the API stores them as
  "encrypted environment variable"
  (https://docs.vast.ai/api-reference/accounts/create-env-var). They are
  encrypted only at rest at Vast and plain env inside each container.
- `--onstart FILE` in CLI 1.7.0 just reads the file into the same `onstart`
  field (`vastai/cli/commands/instances.py:84-86`). The current source does
  not explain the 2026-09-20 failure noted in gpu-workers.md ("only Vast's
  stub arrived").
- `PROVISIONING_SCRIPT` (a URL fetched at start) exists only for Vast's own
  base images (https://docs.vast.ai/guides/templates/advanced-setup).

### 5. F2/F3: server-side guards

Vast documents no server-side auto-destroy or maximum duration for a rented
instance. `--cancel-unavail` only covers F3's "parked from the start" case:
creation fails instead of leaving a stopped instance. The instance JSON has no
image-pull progress: `status_msg` can show a failed pull but not a slow one.
Vast can, however, push lifecycle events (outbid, stopped, error, deleted) to a
webhook.

- DOCUMENTED: `--cancel-unavail` means "Return error if scheduling fails
  (rather than creating a stopped instance)"
  (`vastai/cli/commands/instances.py:143`). The API reference says: "Whether
  to cancel if instance cannot start immediately. Defaults to false for
  interruptibles. Defaults to true for on-demand with target_state='running'",
  and failure is HTTP 410 `no_such_ask`
  (https://docs.vast.ai/api-reference/instances/create-instance). Not tested.
- DOCUMENTED: the only end date is the host's offer end (the "rental end
  date"). At expiry the instance is stopped, not destroyed, and "may be
  deleted 48 hours after expiration"
  (https://docs.vast.ai/guides/reference/faq/instances,
  https://docs.vast.ai/guides/instances/manage-instances). VERIFIED that this
  is no use as a guard: 53710757's `end_date` was 1811568180 (2027-05-29).
- DOCUMENTED: scheduled jobs exist: `POST /api/v0/commands/schedule_job/` takes
  any `api_endpoint` and `request_method`, at HOURLY/DAILY/WEEKLY frequency
  (`vastai/cli/util.py:608-631`). The CLI uses it only for reboot, execute,
  change bid and cloud copy. UNKNOWN: whether it accepts `DELETE
  /instances/<id>/`. If it does, it could act as a server-side dead-man
  switch. To settle, schedule one on a cheap rental and check the audit log.
- DOCUMENTED: on-demand instances are "never interrupted". Interruptible ones
  "May be paused if outbid or if on-demand requested" and resume
  automatically (https://docs.vast.ai/guides/instances/choosing/instance-types).
  On-demand rentals remove the outbid cases (F3/F6) but do nothing for F2 or
  F4.
- Pull progress, VERIFIED (`docs/webapp.md:262-268`, polls in late
  September): while loading, `status_msg` is null and `disk_usage` is -1.
  After the pull `status_msg` reads "Successfully loaded <image>", then
  "success, running <image>/ssh". DOCUMENTED: the CLI's self-test classifies
  `status_msg` errors that match
  `pull|manifest|not found|unauthorized|denied…` as DOCKER_PULL_FAILED
  (`vastai/cli/self_test/runtime_diagnostics.py:246-254,429-450`). So a
  watcher can catch hard pull errors early. For a stall, the only signal is
  time spent in `loading` against the host's `inet_down`.
- DOCUMENTED: notification webhooks. Events include "Instance outbid",
  "Instance stopped", "Instance resumed", "Instance deleted", "Instance error
  detected" (e.g. a container that failed to start) and "Instance offline".
  Deliveries are signed POSTs (HMAC-SHA256), at least once with retries, with
  a 10 s timeout; each user may have at most 4 webhooks, on public HTTPS
  endpoints only (https://docs.vast.ai/guides/reference/notifications,
  https://docs.vast.ai/guides/reference/notification-webhooks).
- VERIFIED: our CLI key is scoped. `GET /api/v0/notification-types/` returns
  401 "lacks the api.notification-types route access". Setting up a webhook
  needs the console or a key with that permission.

### 6. Offer filtering for a host blocklist

All of these filters work on the server:

- `machine_id notin [..]` and `machine_id!=N`;
- `host_id notin [..]` and `host_id!=N`;
- `public_ipaddr notin [..]` and `public_ipaddr!=IP`. The CLI prints
  "Unrecognized field" for this one, but the server applies it.

The identifying fields are:

- `machine_id`: one physical box;
- `host_id`: the operator's account;
- `public_ipaddr`: the site, which several machines can share;
- `geolocation`: region text.

`inet_up` and `inet_down` can be filtered on, but they are self-reported and
did not predict the slow site.

- DOCUMENTED: the query grammar is `field op value`, with ops
  `<, <=, ==, !=, >=, >, in, notin` and lists written `[a,b]`
  (https://docs.vast.ai/cli/reference/search-offers; parser in
  `vastai/api/query.py:279-397`). The documented fields include `machine_id`,
  `inet_up`, `inet_down`, `geolocation` and `static_ip`. `host_id` is in the
  CLI's `offers_fields` (`vastai/api/query.py:109-160`) but not in the docs
  table. `public_ipaddr` is in neither, which causes the warning
  (`query.py:353`).
- DOCUMENTED: "A machine is a single physical host system … One machine can
  publish one or more offers" (https://docs.vast.ai/guides/concepts). Instance
  rows also carry `machine_id`, `host_id`, `public_ipaddr` and `geolocation`
  (https://docs.vast.ai/api-reference/instances/show-instance).
- VERIFIED with gpu-session.sh's query, `--type=bid -o dph_total --raw`:
  - `machine_id notin [26018,33061]`: both missing from the results.
    `machine_id!=26018`: 26018 missing, 33061 present.
  - `host_id notin [3497,135723]`: both missing. `host_id!=3497`: 3497
    missing, 135723 present.
  - `public_ipaddr!=185.62.108.226` and `public_ipaddr notin
    [185.62.108.226]`: that IP was missing in 4 of 4 runs, while the plain
    query returned it twice in 2 of 2 runs. `public_ipaddr=174.164.26.93`
    returned only that site.
  - `inet_up>800`: the lowest `inet_up` in the results was 853.
- VERIFIED: one site can hold several machines. 185.62.108.226 is host 3497
  with machines 8966 and 11877. 92.97.193.95 (host 153828) now offers machine
  152018, and earlier the same IP offered machine 142061.
- VERIFIED: the slow-bucket site 174.164.26.93 (host 22965, machine 147521,
  "Washington, US") advertises inet_down 861.6 and inet_up 853.0 Mbit/s with
  reliability 0.995. On 2026-10-01 it fetched from Scaleway fr-par at
  2–12 KB/s. The good host 92.97.193.95 advertises inet_up 485.7. `inet_up`
  describes the host's link, not its route to our bucket.
- VERIFIED: identical queries seconds apart returned 16–18 offers, partly from
  different machines (the server endpoint is `POST /api/v0/bundles/`,
  `vastai/api/offers.py:53`). Put the blocklist in the query, so excluded
  hosts cannot crowd out the "random among the 5 cheapest" pick.

### 7. Billing

Storage is billed from creation until destroy, in every state except
host-offline: loading, stopped and outbid all count. GPU time is billed only
while the instance runs. Destroying an instance does not end billing at once:
across our 34 rentals, billing continued for up to ~5 min after the DELETE.

- DOCUMENTED: "You are charged the storage cost … for every single second
  your instance exists and is online (for all states other than offline).
  Stopping an instance does not avoid storage costs."
  (https://docs.vast.ai/guides/reference/billing). Also: "Storage charges
  begin at creation. GPU charges begin when status reaches `running`"
  (`vastai/SKILL.md:152`), and an outbid instance is stopped while storage
  billing continues (`SKILL.md:158`). One page contradicts this: "Do I pay
  for Loading instances? No"
  (https://docs.vast.ai/guides/instances/manage-instances).
- VERIFIED: loading is billed for storage. 53689346 and 53690819 never ran
  (0 GPU hours) but were billed 0.201 h and 0.109 h of disk.
- VERIFIED (first DELETE time in the audit log against billed hours from
  `show invoices-v1 --charges`, for 2026-09-20, 2026-09-22 and 2026-10-01):
  - Storage ran from 22 s before to 290 s after the DELETE (median ≈ +2 min).
  - 53709084 lived 80 s from create to DELETE, but was billed 0.088 h
    (≈5.3 min) of GPU time.
  - The already-stopped 53710757 stopped billing at its DELETE (−2 s).
  - The tail costs fractions of a cent.

### Implications for the design

- Keep the watchdog's `DELETE`: it destroys the instance. It cannot cover a
  stopped instance, because the watchdog dies with the container, so F7
  needs an account-side sweeper. The sweeper runs `show instances --raw` and
  destroys any instance with our label that has `intended_status=stopped`,
  has `actual_status` in exited/unknown/offline, or is older than an age cap.
- Make the watchdog log curl's HTTP status somewhere durable, and repeat the
  2026-09-20 self-destruct test on the current image to close §1's UNKNOWN.
- Label every rental at creation (`--label <song>/<version>`). Reconcile with
  `show instances --label …`, and only destroy ids returned by that call
  (bucket contents are untrusted).
- Use the §2 rule in wait loops. Treat empty stdout, or stderr with `"error":
  true`, as "unknown, retry", not as gone; the CLI exits 0 in every case.
- Pass `--cancel-unavail` at creation. A bid that cannot start then fails at
  once with 410 instead of parking as `stopped` (F3). Test this first.
- F2 still needs a give-up on our side, since Vast has no server-side TTL.
  Destroy when `status_msg` shows a pull error, or when time in `loading`
  exceeds `45 s + 6 × 8 GB / inet_down` plus a margin. A cheap rental can
  test whether a scheduled-job DELETE works as a server-side backstop.
- A Vast webhook (outbid/stopped/error/deleted) aimed at the Scaleway app
  would wake the container to reconcile, because each delivery is a request.
  It needs the console or a key with notification permission.
- An autonomous worker started from onstart is feasible: the worker fits in
  4048 chars with gzip+base64. Because onstart re-runs on resume, the worker
  must stay idempotent. The S3 key in `--env` can be read through `show
  instance` and by the host, as today.
- Put the blocklist in the offer query: `public_ipaddr notin [...]` for
  slow-route sites and `machine_id notin [...]` for broken boxes. Keep the
  measured bucket test, since `inet_up` does not replace it.
- Count storage from creation in spend caps, plus a few minutes after each
  destroy.
- Still open (one cheap test rental would settle most of these): the
  container key's scope, scheduled-job DELETE, the label charset, the `--env`
  size limit, and `--cancel-unavail` on bids.

## Part C — the code

Code facts behind [gpu-resilience-handoff.md](gpu-resilience-handoff.md),
requirements 4 and 5, plus the touch points a job record would replace. Line
numbers are at commit `df91919`. Library line numbers refer to atom's
`.venv` (demucs 4.1.0, audio-separator 0.47.0, soundfile 0.14.0). The GPU
image resolves these unpinned at build time (`Dockerfile.gpu:20`).

### 1. Stage caching and write atomicity

Every skip is a bare existence check, and none of the pipeline's own writes
use temp + rename. A crash can leave four skip-gated outputs truncated:
the worker's source download, Demucs `no_drums.flac`, `beats_raw.json` and
`onsets.json`. The MDX23C kit stems are atomic. Everything after
`onsets.json` is rewritten on every run, so a rerun repairs it. Nothing
triggers that rerun, though, because a truncated `sonification.ogg` already
counts as "ready".

Order inside `cli.run_pipeline` (`cli.py:89-188`). The variants share
stages 0–3. After that, adtof, mdx23c and fused differ only at step 4.

| # | stage | output | skip when | write | truncation risk |
|---|---|---|---|---|---|
| 0 | worker fetch | `source.<ext>` | `[ -e "$src" ]` (`vast-worker.sh:42`) | `curl -o` in place, no timeout | **Yes.** A retry on the same host skips a partial source, and every later stage caches results computed from the truncated audio |
| 0a | container fetch | `source.*` | — (runs once per job) | urllib → `fetched*` in place, then `rename` (`ingest.py:239-252`). ffmpeg → `source.m4a` in place (`ingest.py:256-261`) | ffmpeg case yes. Today no code path re-fetches, so it never shows up |
| 0b | browser upload | `upload.<ext>` | — | in place. On EOF the loop just `break`s and the job starts anyway (`serve.py:1820-1827`) | a short upload gets processed as if complete |
| 1 | copy source | `source.*` | exists (`cli.py:114-116`) | `shutil.copy2` | no-op in practice: the input already is `source.*` |
| 2 | Demucs (all variants) | `stems/htdemucs/source/drums.flac`, `no_drums.flac` | both exist (`separate.py:23`) | ffmpeg subprocess writes straight to the final path (`demucs/audio.py:263-276, 315-316`). drums first, no_drums second (`demucs/separate.py:212, 225`) | **Yes, for `no_drums.flac`.** A crash while it is being written leaves both files present, so the stage is skipped forever. A crash during `drums.flac` is redone, because no_drums doesn't exist yet |
| 3 | beat_this | `beats_raw.json` | exists and no `--force` (`cli.py:131`) | `write_text` in place (`beats.py:31-37`) | **Yes.** A truncated file raises a JSON error on every run (stuck, not silently wrong). It also breaks `/api/index` for **all** projects, because `scan_output` loads it with no try (`serve.py:1561-1569`) |
| 3a | grid | `beats.json` | never skipped (`cli.py:137-139`) | in place | rewritten every run. Pages read it meanwhile |
| 4 | adtof onsets | `adtof/onsets.json` | exists and no `--force` (`cli.py:144`) | `write_text` in place (`transcribe.py:29-30`) | **Yes.** Stuck on a JSON error. `_rerun` also picks variants by this file's existence (`ingest.py:156`) |
| 4 | mdx23c: kit split + per-stem onsets | `stems/mdx23c/{kick,snare,tom,hihat,ride,crash}.flac`, `mdx23c/onsets.json` | stems: all 6 `<name>.*` exist (`separate.py:44-50`). onsets: as above | separator writes temp + `os.replace` (`audio_separator/separator/audio_io.py:47-67`) to a `(kick)`-tagged name, which our code then renames (`separate.py:62-68`) | stems: no. onsets: as adtof |
| 4 | fused: kit split (cached), ADTOF, refine | `fused/onsets.json` | as above | as above | as adtof |
| 5 | quantize | `<v>/events.json` | never | in place (`quantize.py:42`) | repaired by a rerun. A truncated file also breaks `/api/index` (`serve.py:1547`) |
| 6 | MIDI | `audition.mid` | never | pretty_midi in place (`audition.py:38`) | repaired by a rerun |
| 7 | sonify | `sonification.ogg` | never | soundfile in place (`sonify.py:61`) | repaired by a rerun, **but counts as ready** (`progress.py:89`) |
| 8 | score | `score.musicxml` | never | music21 in place (`score.py:154`) | repaired by a rerun |
| 9 | export | `score.mscz`, `mscz-problems.txt` | never. Both are unlinked first (`export.py:59-60`) | written by MuseScore, 600 s timeout (`export.py:33`) | repaired by a rerun. Optional output (`cli.py:185-187`) |

Writers that don't touch the cache: beat_this, ADTOF and librosa write
nothing (ADTOF's MIDI goes to `/dev/null`, `transcribe.py:52`).

Transfer layer:

- Worker: `set -euo pipefail` (`vast-worker.sh:16`). `rclone copy` runs
  only after `drum-transcribe run` exits 0 (`vast-worker.sh:44-52`), so a
  crashed variant uploads nothing. A host that dies **during** the copy
  leaves a partial set. Each object PUT is atomic, but the transfers run in
  parallel in no defined order.
- Downloads are atomic: s3transfer writes a temp file and renames it
  (`s3transfer/download.py:153-184`). Both `gpu-session.sh:148` and
  `sync_bucket.py:47` use it.
- On a cold start, `sync_bucket.py:40-41` turns every audio key into a
  0-byte stand-in. Stand-ins pass every existence check: `separate.py:23`,
  `progress.py:86-88`, `ingest.py:154`.
- Not a pipeline stage, but user data: `feedback.json` is written with
  `write_text` in place (`serve.py:1798`).

### 2. "Variant ready" and progress

A variant counts as ready once `<v>/sonification.ogg` exists. The job state
comes from the in-memory `RUNNING` set plus the text of `pipeline.log`.
Locally, the last file the pipeline always writes is `score.musicxml`
(`score.mscz` comes after it but is optional). In the bucket, no existing
file can serve as a completion marker, because `rclone copy` uploads in no
defined order. A dedicated marker has to be uploaded by a separate command
after the copy succeeds.

Evidence (`progress.version_progress`, `progress.py:79-114`):

- Ready flags (`:86-89`):
  - `src`: any `source.*` exists.
  - `drums`: both `drums.flac` **and** `no_drums.flac` exist.
  - each variant: `<v>/sonification.ogg` exists.
- `running` is passed in as `vdir in ingest.RUNNING` (`serve.py:1585, 1654`).
- Job states (`:90-101`):
  - `running`: a thread is going.
  - `stopped`: text after the last `== all pipelines finished ==`/`ERROR:`
    marker, and no thread.
  - `failed`: the last end marker is `ERROR:`.
  - `None`: none of the above, including when there is no log at all.
- For stopped/failed, each task that isn't ready is listed with that state
  (`:102-104`). A running job's estimates are parsed from the log markers
  (`_running`, `:117-169`). A task whose result exists gets no bar (`:164-165`).
- `sig` covers `source.*`, both FLACs, `*/sonification.ogg`,
  `*/score.musicxml`, `beats.json` and `keep-raw-bars` (`:108-113`). The
  page re-renders when it changes (`serve.py:1125-1128`).
- Page side:
  - A variant is listed only if `<v>/events.json` exists (`serve.py:1543-1546`).
  - The sonification player needs `files["sonification.ogg"]`
    (`serve.py:809-814`). Otherwise a progress bar.
  - A score tab needs `files["score.musicxml"]` (`serve.py:994-995`).
    Otherwise the placeholder "appears when adtof finishes" with a bar
    (`:1011-1013`).
  - A bar with no task shows "Not made for this version", and "stopped"
    shows "Interrupted: the server restarted…" (`serve.py:1100-1102`).
  - Polling stops when no job is `running` (`serve.py:1062, 1131-1133`).

How files reach the cloud container:

- At the end of a job, `gpu-session.sh:133-151` syncs the version after
  **all** variants are done. Keys come in lexicographic order, downloaded
  one at a time. Within a variant: `events.json` < `onsets.json` <
  `score.musicxml` < `sonification.ogg`. The shared `beats*.json`,
  `source.*` and `stems/` arrive *after* `adtof/`.
- On a cold start, the sync finishes before the server starts
  (`container-start.sh:32-33`).

So the page shows a half-uploaded variant only when the bucket itself holds
a partial set (F6, the host died mid-`rclone`). The container sees that set
after its next cold start. By then `pipeline.log` is gone, because it is
never uploaded, so the job state is `None` and nothing polls or resumes.

- **`sonification.ogg` present, `score.musicxml` missing** (with
  `events.json`): the sonification plays and the variant counts as done.
  The variant has no score tab. If no variant has a score, the placeholder
  bar says "Not made for this version". Nothing resumes it.
- **`sonification.ogg` present, `events.json` missing**: the variant isn't
  listed. Its row shows a bar saying "Not made for this version", although
  the `.ogg` is on disk. Local recording doesn't offer it as backing either
  (`local-recording.js:154-161`).
- **`score.musicxml` present, `sonification.ogg` missing**: the score tab
  shows, and the sonification row shows a bar. If a `pipeline.log`
  without an end marker survives, it says "Interrupted"; otherwise "Not made
  for this version".

Natural completion marker: per variant, the write order is
`onsets.json` → `events.json` → `audition.mid` → `sonification.ogg` →
`score.musicxml` → `score.mscz`/`mscz-problems.txt` (`cli.py:162-176`).
This order says nothing about the bucket. Use a marker object such as
`<v>/done`, uploaded with its own `rclone copyto` or PUT after
`rclone copy` exits 0. Locally, the CLI writes the same file as its last
step after `to_mscz`. The adtof upload also carries the shared files
(source, Demucs stems, beats), so adtof's marker covers them as well.

### 3. CPU offload candidates for the web container

None worth it. Every candidate starts from `onsets.json`, which exists only
after the GPU's ADTOF or MDX23C step. The steps after it take seconds on the
GPU host: the CPU estimate for all of "writing outputs" is 1 s + 0.01 s per
second of song (`progress.py:33-35`). `quantize` and `beats.regularize`
already run there unchanged. While the GPU host loads, the useful CPU work is
fetching and uploading the source in parallel with renting, not pipeline
stages.

The web image (`deploy/Dockerfile`): python:3.12-slim + apt `openssh-client
ffmpeg` (`:5`). The package is installed `--no-deps`, plus `numpy boto3
vastai yt-dlp` only (`:11`). None of vastai's dependencies is an audio or
music library. All stage imports in `cli.run_pipeline` are deferred
(`cli.py:90-107`), and module top-levels import only numpy, so the CLI
itself imports fine in that image.

| module | imports (transitive) | runs in the web image? | to make it run | inputs |
|---|---|---|---|---|
| `beats.regularize` | numpy (`beats.py:7`) | **yes**, already runs on every `/api/index` (`serve.py:1567`) | — | `beats_raw.json`, `keep-raw-bars` |
| `quantize.py` | numpy, `.beats`, `.transcribe` (whose librosa/adtof imports sit inside functions, `transcribe.py:43, 79, 120, 151`) | **yes** | — | `onsets.json`, grid |
| `audition.py` | `pretty_midi` inside the function (`audition.py:24`) → mido, six, importlib_resources | no | pip `pretty_midi` (~6.5 MB with mido) | events |
| `score.py` | `music21` inside functions (`score.py:60, 71-72`) → matplotlib, joblib, jsonpickle, requests, webcolors, chardet, more-itertools | no | music21 (112 MB installed incl. corpus) + matplotlib (25 MB) | events, meter |
| `sonify.py` | numpy at top. librosa + soundfile inside the function (`sonify.py:45-46`). librosa pulls scipy, numba/llvmlite, scikit-learn (~330 MB locally) | no | replace `librosa.load` with an ffmpeg decode pipe (`-ac 1 -ar 48000 -f f32le`). Encode with soundfile (3.7 MB, bundled libsndfile does Opus) or ffmpeg | events + **original audio**. After a cold start that is a 0-byte stand-in, so it must be fetched from the bucket |
| `export.py` | MuseScore CLI via subprocess (`export.py:57`) | no. The AppImage is only in the GPU image (`Dockerfile.gpu:27-32`) | not feasible | `score.musicxml` |

Memory: a 6-min mono 48 kHz float32 array is ~70 MB, and sonify holds two,
which fits in 1 GB. CPU time on 0.5 vCPU was not measured.

### 4. Playback stems

The page, the progress code and the scan read the stems by `.flac` glob.
The pipeline reads `drums.flac` as input only when a variant's
`onsets.json` is missing, and never reads `no_drums.flac`. But
`separate_drums` is called on every run (`cli.py:121`), and its cache check
names the `.flac` files (`separate.py:21-23`). If only Opus copies were
present, every run would recompute Demucs, even a meter rerun. Encoding
Opus at sonify's setting gives 106 kbit/s per channel. That makes the stem
pair 7× smaller in stereo, 14× in mono.

Readers:

- **Server**:
  - `scan_output` globs both files (`serve.py:1539-1540`) → `drums`/`drumless` URLs (`:1579-1581`).
  - `/files/` redirects 0-byte audio to a presigned bucket URL (`serve.py:1673-1679`, any suffix in `AUDIO_EXTS`, `ingest.py:23`, which includes `.ogg` and `.opus`).
  - Content-Type comes from `guess_type` locally (`serve.py:1691`). In the cloud it comes from the S3 object's metadata, set by rclone at upload.
- **Progress**: ready check and sig (`progress.py:86-88, 108-109`).
- **Page JS**:
  - players `audioTag(v.drums)`, `audioTag(v.drumless)` (`serve.py:985-988`)
  - the download `download="${PROJECT}-${v.name}-without-drums.flac"`, label "Download FLAC", tooltip "Lossless audio for Android and Ableton Live" (`serve.py:989-991`)
  - help text "Download the lossless FLAC…" (`serve.py:675`)
  - mobile menu "Without drums (FLAC)" (`static/mobile.js:231-234`)
  - local-recording backing via `decodeAudioData` (`static/local-recording.js:154-161, 777, 1177`). This is format-agnostic. The page already plays Ogg Opus sonifications, so Opus stems add no new browser requirement.
- **Docs**: README "Download FLAC… 24-bit… imports into Ableton Live" (`README.md:103-108`), `AGENTS.md:44-46`, `docs/webapp.md:36-38`, `docs/gpu-workers.md:92`.
- **Worker upload filter** names the FLACs (`vast-worker.sh:48-49`).

Pipeline inputs on a later run:

- `drums.flac`:
  - ADTOF (`cli.py:155, 160`)
  - `estimate_velocities` (`cli.py:161`)
  - MDX23C split (`cli.py:148, 153`)

  All of these run only when `<v>/onsets.json` is missing (`cli.py:144`).
- The kit stems feed fused (`refine_with_stems`, `cli.py:157`) and mdx23c
  onsets (`cli.py:150`), also only when onsets are missing.
- Sonification mixes the **source**, not the stems (`cli.py:173`).
- A meter rerun reads no audio except the source.

Changes needed if the uploaded playback copies were Opus:

- File names in `scan_output`, `progress.py` and the worker filter.
- The download name, label and help text. They promise lossless FLAC, and
  Opus breaks that promise (user's call; whether Ableton imports Opus is
  unverified).
- Make `separate_drums` lazy: call it only when `onsets.json` (or the kit
  stems) is missing, or let `.ogg` satisfy its cache check. Otherwise
  `run-on-gpu.sh` results synced to the laptop make every rerun recompute
  Demucs: 2 s + 0.34 s per second of song on CPU (`progress.py:55`), ~1.6
  min for a 4.6 min song.
- Use the `.ogg` suffix, as sonification does. Python's `mimetypes` maps it
  to `audio/ogg`. `.opus` → `audio/ogg` on atom (via the system mime.types).
  The container's and rclone's mapping is unverified.

Measured (`ffprobe` durations, file sizes; 44.1 kHz stereo):

| version | length | drums.flac | no_drums.flac | FLAC pair | Opus pair @214 kbit/s (stereo) | @107 kbit/s |
|---|---|---|---|---|---|---|
| dancing-through-life/taustanauha | 3.2 min | 31.7 MB (1319 kbit/s, 24-bit) | 33.2 MB (1382) | 64.8 MB | 10.3 MB | 5.1 MB |
| dancing-through-life/obc | 7.6 min | 33.2 MB (580, 16-bit, older run) | 82.7 MB (1445) | 115.8 MB | 24.5 MB | 12.2 MB |
| highway-star/levyversio | 6.1 min | 73.6 MB (1603) | 69.7 MB (1517) | 143.3 MB | 19.7 MB | 9.8 MB |
| wake-up-…/atlus-sound-team-youtube | 4.6 min | 54.3 MB (1565) | 50.3 MB (1449) | 104.7 MB | 14.9 MB | 7.4 MB |
| the-police-nothing-achieving/hd2 | 1.9 min | 21.4 MB (1466) | 21.0 MB (1439) | 42.3 MB | 6.2 MB | 3.1 MB |

Sonify's Opus setting: `compression_level=0.6` (`sonify.py:61`, the comment
says "~110 kbps"). That is a per-channel target in libsndfile.

- Existing `adtof/sonification.ogg` files (mono) measure 107–125 kbit/s.
- I re-encoded 120 s of highway-star's stems at the same setting: 107
  kbit/s mono, 214 kbit/s stereo.
- highway-star's adtof upload today: source 12.3 MB + FLAC pair 143.3 MB +
  ~6.5 MB of variant files. The FLACs are ~88 % of it. With Opus stereo it
  would be ~39 MB.

### 5. The rerun path

Only the meter switch triggers a rerun. It reruns `cli run` for each variant
that has `onsets.json`. With stems, `beats_raw.json` and onsets present,
nothing needs torch: regrid → quantize → MIDI → sonification → MusicXML →
mscz. Today it cannot run in the cloud. It fails at `import pretty_midi`
after it has already rewritten `beats.json` and `events.json`. The cloud
app never needs the FLAC or MDX23C stems. The only check is file existence,
and the 0-byte stand-ins pass it. It would need the source audio for
sonification.

Evidence:

- Trigger: `POST /api/rawbars` → `_set_raw_bars` touches or unlinks
  `keep-raw-bars`, then `start_rerun_job` (`serve.py:1736-1740,
  1775-1783`). Feedback doesn't rerun. `_rerun` (`ingest.py:152-160`) takes
  `source.*` (`:154`) and runs each variant with `onsets.json` (`:156`) as a
  subprocess (`ingest.py:65-72`).
- What one rerun does, per variant:
  - `separate_drums`: existence check only (`cli.py:121`, `separate.py:23`)
  - beats: cached load (`cli.py:131-132`)
  - `beats.json` rewritten (`:137-139`)
  - onsets: cached (`:144-145`)
  - then `events.json`, `audition.mid`, `sonification.ogg`,
    `score.musicxml`, `score.mscz` (`:165-176`)
- In the web image:
  - The imports succeed (§3).
  - `beats.json` and `events.json` are rewritten.
  - `write_audition_midi` raises `ModuleNotFoundError: pretty_midi`
    (`audition.py:24`, `Dockerfile:11`), and `_rerun` logs `ERROR:`.
  - Result: new grid and events, but old MIDI, sonification and score. The
    page's bar overlay (from `beats.json`) and the old score disagree.
- Even if the rerun ran, sonification would need the real source (a
  stand-in after a cold start), and `.mscz` would need MuseScore. In the
  cloud it would have to be dropped or marked stale.
- Not persisted in the cloud: the `keep-raw-bars` flag (`serve.py:1778-1782`),
  the rerun outputs and `feedback.json` (`serve.py:1798`). None of them goes
  through `gate.keep`, which is called only for `created` and
  `source-url.txt` (`serve.py:1716-1718`, `gate.py:87-97`). They are lost at
  the next cold start. No doc mentions this.
- The rerun doesn't check `RUNNING` (`serve.py:1775-1783`). A meter switch
  during a job starts a second pipeline on the same directory. The first
  thread to finish then removes the version from `RUNNING` while the other
  still runs (`ingest.py:38-46`).

### 6. Same-process assumptions (touch points for a job record)

Job existence, arguments, log and GPU instance all live in the container
process or its CWD. These are the places a bucket-backed job record (plus
a persisted log) would replace:

| touch point | where | today |
|---|---|---|
| "job running" | `ingest.RUNNING` (`ingest.py:25`). Added and discarded in `_start` (`:38-46`) | in-memory set; a second job on the same dir corrupts it |
| job runner | daemon `threading.Thread` (`ingest.py:46`). Entry points `start_version_job` (`:33-35`), `start_rerun_job` (`:147-149`) | dies with the process |
| job arguments | `url`, `upload`, `gpu` only as thread args (`ingest.py:75-76`, `serve.py:1719, 1827`) | `source-url.txt` is kept (`serve.py:1717-1718`). The GPU flag and the variant list are not |
| readers of `RUNNING` | `scan_output` progress (`serve.py:1585`), `/api/progress` (`:1654`), delete guard (`:1769`) | the rerun trigger doesn't check it (`:1775-1783`) |
| log writes | `_log` (`ingest.py:49-51`). Subprocess stdout from `_run_variant` (`:67-72`), `_run_on_gpu` (`:139-144`), yt-dlp (`:219-225`), ffmpeg (`:257-261`). Markers (`:28-30`) | local `<vdir>/pipeline.log`, never uploaded |
| log readers | `version_progress` job state (`progress.py:90-101`). `_running` parses markers, `== syncing results` (`:138`), GPU tries (`:144`), `instance running` (`:184`), `Mbit/s` (`:197`). `scan_output` `error` = "ERROR:" in the last 2000 chars (`serve.py:1583`). Log link and gear menu (`serve.py:1582, 1050-1053`) | all disappear on a cold start, so the state reads `None` |
| "stopped" meaning | log without an end marker + no thread (`progress.py:96-97`). The page says "the server restarted" (`serve.py:1100-1101`) | shown, never resumed |
| GPU instance state | `.gpu-instance`, `.gpu-known-hosts` in CWD (`gpu-session.sh:22-23`). `run-on-gpu.sh:14` reuses any live session, and only the job that rented it destroys it (`:21`) | one per container. Two concurrent GPU jobs share an instance, and the first to finish destroys it under the other |
| result arrival | the job's final sync, after all variants (`gpu-session.sh:133-151`). It downloads full FLACs into the container | results reach the page only if the process lives to the end |
| re-submission | `_new_version_dir` refuses an existing dir (`serve.py:1859-1863`) | no UI path to retry a version |
| small-file persistence | `gate.keep` (fire-and-forget thread, `gate.py:94-97`) | the existing hook for writing job records and markers to the bucket |

### Implications for the design

- **Atomic cache writes** are needed in four places:
  - JSON: one helper (temp file + `os.replace`) for `BeatGrid.save`,
    `save_onsets` and `save_events`.
  - Demucs: write into a temp stems dir and rename it into place, or skip
    only when a marker written after both files exists.
  - Worker: `curl -o "$src.part" && mv`.

  Alternatively, treat an unparsable cache file as missing. That also
  protects `/api/index` from one bad file.
- **Completion marker** per variant, uploaded after a successful
  `rclone copy`. `progress` and resume should key on it. Legacy versions
  without a job record keep the `sonification.ogg` rule.
- **No CPU pipeline offload** during the GPU load. Start fetching and
  uploading the source in parallel with renting instead. Making the meter
  rerun work in the cloud is a separate decision. It would need pretty_midi,
  music21 + matplotlib and an ffmpeg-based sonify, and `.mscz` would go
  stale.
- **Opus stems** cut the critical-path upload about 4× (highway-star adtof:
  ~162 → ~39 MB). Before switching, make `separate_drums` lazy and rename
  the files consistently (`.ogg`). The lossless download promise is the
  user's call. One option: upload Opus first for playback and the FLACs
  after the last variant, off the critical path.
- **The cloud app needs no audio stems**, FLAC or MDX23C. The job-end sync
  could skip audio like `sync_bucket.py` does. Uploading `stems/mdx23c/`
  only matters for GPU-side resume of `fused`.
- **The job record** must replace `RUNNING`, the thread args, the local
  `pipeline.log` (append it to the bucket) and `.gpu-instance`. Its lease
  must also cover the meter rerun.
- **Unpersisted cloud state.** `feedback.json`, `keep-raw-bars` and rerun
  outputs are lost on cold start. This is outside the GPU work but the same
  persistence gap.
