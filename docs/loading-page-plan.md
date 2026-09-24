# Plan: "Starting up…" page for plokkaus.vempai.men

Status: built and deployed 2026-09-25 (operations reference: [operations.md](operations.md)).

## What and why

The cloud copy of the web app sleeps when nobody uses it. The first visit
after a pause wakes it up, and until it is awake (measured 2026-09-24:
about 70 s before the startup fixes, at least ~22 s after them, plus
Scaleway's own start time) the browser shows a blank, spinning tab.

The fix is a tiny program that runs on Cloudflare's servers, in front of the
app (a *Cloudflare Worker*). Every visit passes through it. If the app answers
quickly, the visitor sees the app as usual. If it doesn't answer within a
couple of seconds, the Worker shows a "Starting up…" page instead. That page
waits for the app and then reloads itself into the real page.

## How the Worker behaves

For every request to `plokkaus.vempai.men`:

1. **Page loads** (`GET` with `Sec-Fetch-Mode: navigate`, e.g. `/`, `/p/…`):
   send the request to the app and race it against a 2.5 s timer (warm
   answers take ~0.2 s).
   - App answers in time with anything but a 5xx: pass that response through.
   - Timer wins, or the app answers 502/503/504: return the loading page
     (status 503, `Cache-Control: no-store`, `Retry-After: 5`). The
     original request stays alive via `ctx.waitUntil`, so it keeps waking
     the container.
2. **Everything else** (score files, audio redirects, uploads): pass
   through untouched. Only page loads get the loading page; by the time a
   page has loaded, the container is awake anyway.
3. **`/api/*` never reaches the Worker.** A second route,
   `plokkaus.vempai.men/api/*`, is set to "no Worker", so these requests
   go through Cloudflare's plain proxy straight to the app. That covers the
   once-a-second polls (`/api/seek`, `/api/progress`), which would
   otherwise use up the free plan's daily Worker allowance, as well as
   unlock and create. It also covers the loading page's own `/api/seek` check.

Passing through is `fetch(request, { redirect: "manual" })`. The request
goes to the existing DNS target with the `Host` header unchanged, so:

- the app sees exactly what it sees today;
- the audio 302 redirects to bucket links reach the browser as they are;
- the `create_token` cookie keeps working (it is scoped to
  `plokkaus.vempai.men`, which is still what the browser sees);
- nothing in the app uses the client IP (checked: `gate.py` counts
  markers, not addresses), so seeing Cloudflare's addresses instead is fine.

### The loading page

A small HTML page with no external files, inlined in the Worker. It uses the
style guide colours and shows "Starting up… (usually under a minute)" plus a
seconds counter. Its script:

```js
for (;;) {
  try { if ((await fetch("/api/seek", {cache: "no-store"})).ok) break; }
  catch {}
  await new Promise(r => setTimeout(r, 2000));
}
location.reload();
```

`/api/seek` is the cheapest endpoint the app already has, and it has no side
effects. It skips the Worker (the `/api/*` route), so the fetch simply waits
at the proxy while the container starts. The reload
goes through the Worker again, which by then passes the real page through.

## Files

```
deploy/cloudflare/worker.js      # the Worker + inlined loading page (~60 lines)
deploy/cloudflare/wrangler.toml  # name, compatibility_date, route
```

`wrangler.toml`:

```toml
name = "plokkaus-front"
main = "worker.js"
compatibility_date = "2026-09-24"
routes = [{ pattern = "plokkaus.vempai.men/*", zone_name = "vempai.men" }]
```

Using a *route* rather than a Worker "custom domain" keeps the existing DNS
record and the Scaleway domain binding as the origin. Rolling back then
means turning one switch off (see below).

The `/api/*` exclusion can't be written in `wrangler.toml` (a route there
always names this Worker). It is created once through the Cloudflare API:
`POST /zones/<zone_id>/workers/routes` with
`{"pattern": "plokkaus.vempai.men/api/*"}` and no `script`. The more
specific pattern wins over `plokkaus.vempai.men/*`.

## Deployment

One-time setup, done by you in the Cloudflare dashboard:

1. Create an API token from the "Edit Cloudflare Workers" template, limited
   to the `vempai.men` zone, and add "Zone → DNS → Edit" for the same zone.
   Save it with the account ID in `.secrets.cloudflare.env`
   (`CLOUDFLARE_API_TOKEN=…`, `CLOUDFLARE_ACCOUNT_ID=…`; `.secrets*` is
   gitignored) and in the password manager (update
   [recovery.md](recovery.md)).

Then the agent:

2. Tests locally: `npx wrangler dev --local-upstream localhost:8799` against
   a stand-in app that sleeps 20 s before answering. Checks that the loading
   page appears, reloads itself, and that API calls, 302s and cookies pass
   through.
3. Deploys: `cd deploy/cloudflare && npx wrangler deploy`.
4. Switches the `plokkaus` DNS record from "DNS only" to "Proxied" (Cloudflare
   API). The route only runs for proxied records, so this step turns the
   Worker on.
5. Creates the `/api/*` "no Worker" route (above) and sets the main
   route's failure mode to "fail open" (see limits below).
6. Verifies the live site with a browser: page, audio playback and seeking,
   password unlock, a small upload. Checks in the Cloudflare dashboard that
   `/api/seek` polls don't show up as Worker requests. Then waits for a real cold start and
   checks that the loading page appears.
7. Documents it in [operations.md](operations.md) (cloud section) and adds
   one plain sentence to the README.

**Rollback:** switch the DNS record back to "DNS only". The Worker is
bypassed immediately and everything works as it does today.

## Limits and risks

- **Free plan: 100 000 Worker requests a day.** Only page loads and file
  requests count, because the once-a-second polls go through the `/api/*`
  route and never reach the Worker. Normal use stays far below the limit.
  As a safety net, "fail open" makes requests over the limit skip the Worker
  and go straight to the app. Only the loading page is lost.
- **Uploads over 100 MB fail** through Cloudflare's proxy (free plan limit).
  Song MP3s are far below that, but a long WAV or video upload might not be.
  Checked 2026-09-25: Scaleway alone accepted a 120 MB request, so this is a
  new limit. If big uploads matter, uploads would need to go straight to the
  bucket. That is a separate change.
- **HTTPS certificate:** Scaleway renews its `plokkaus` certificate itself.
  Behind the proxy, the renewal's check passes through Cloudflare, which
  normally lets `/.well-known/acme-challenge/` through ("Always use HTTPS"
  is off in the zone). Even if a renewal fails, the zone's SSL mode was
  already "Full" (not strict), which accepts an expired origin certificate.
- **Proxy timeout 100 s:** Cloudflare gives up on an origin that hasn't
  answered in 100 s (error 524). Page loads never hit it (the loading page
  answers after 2.5 s). The loading page's `/api/seek` poll just retries.
- **Cost:** none on the free plan.
