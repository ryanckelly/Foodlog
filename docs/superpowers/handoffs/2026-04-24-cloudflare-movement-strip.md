# Handoff: Cloudflare is silently stripping one `<section>` from `/dashboard/feed`

> **RESOLVED 2026-04-24.** Root cause was NOT Cloudflare. Two orphaned one-off containers (`foodlog-foodlog-run-eea7a4a8…` and `foodlog-foodlog-run-469f3148…`) were running an older image of the app AND registered against the same Cloudflare tunnel (shared `TUNNEL_TOKEN`). Cloudflare load-balanced public requests across all three connectors; whenever a stale container won the round-robin, the client got a pre-Movement-section response. Loopback always hit the named live container because the port mapping only points there. Fix: stopped the orphaned containers. Takeaway: never use `docker compose run` (or `docker run` with this image) for diagnostics — it registers a duplicate tunnel connector. See also `~/.claude/projects/-opt-foodlog/memory/feedback_docker_compose_run_duplicates_tunnel.md`. The investigation log below is retained for context.

**Status (at time of writing):** unresolved after ~2 hours of diagnosis.
**Target agent:** Codex (or any fresh debugger).
**Time pressure:** none; dashboard works over LAN via `127.0.0.1:3474`; only the public-hosted path is broken.

---

## One-line problem

`GET https://foodlog.ryanckelly.ca/dashboard/feed?date_range=today` returns a byte-for-byte identical 5484-byte response regardless of backend changes. The backend (verified via `127.0.0.1:3474`) returns 5939 bytes including a `<section class="movement-section">` partial. Cloudflare is deterministically removing that section (~455 bytes) before the response reaches the client. The cut is clean at the `</section>` closing tag of the meals block; nothing after it survives.

## Repo & runtime

- Repo: `/opt/foodlog` (branch `main`, commit `10498bc` — do `git log | head -20` to see the full Google Health integration history).
- Single Docker container `foodlog` running FastAPI + cloudflared sidecar (see `docker-compose.yml`).
- Public URL: `https://foodlog.ryanckelly.ca` (Cloudflare Tunnel → `http://localhost:3474` inside the container).
- Google SSO gate protects `/dashboard` routes.
- Session cookie secret is in `/opt/foodlog/.env` as `FOODLOG_SESSION_SECRET_KEY`.

## The exact observation

Backend loopback (`http://127.0.0.1:3474`):
- `/dashboard/feed?date_range=today` → 200, **5939 bytes**, tail ends with the Movement partial and `</section>`.

Public edge (`https://foodlog.ryanckelly.ca`):
- `/dashboard/feed?date_range=today` → 200, **5484 bytes**, tail ends one section earlier at the meals `</section>`.

`diff` between the two is the entire Movement partial (plus a leading blank line). The 5484-byte response is **byte-identical** across multiple requests with different cache-busting query params — `sha256sum` matches exactly. This is the single strongest clue: it looks like a cached response, yet `cf-cache-status: DYNAMIC` is returned.

## Repro commands

```bash
COOKIE=$(docker exec foodlog python -c "
import base64, json, itsdangerous, os
signer = itsdangerous.TimestampSigner('$(grep ^FOODLOG_SESSION_SECRET_KEY /opt/foodlog/.env | cut -d= -f2)')
payload = base64.b64encode(json.dumps({'user':'ryan.c.kelly@gmail.com'}).encode()).decode()
print(signer.sign(payload.encode()).decode())
")

# 5939 bytes, Movement present
curl -s "http://127.0.0.1:3474/dashboard/feed?date_range=today" -H "Cookie: session=$COOKIE" | wc -c

# 5484 bytes, Movement missing
curl -s "https://foodlog.ryanckelly.ca/dashboard/feed?date_range=today&t=$(date +%s%N)" -H "Cookie: session=$COOKIE" | wc -c
```

## What we have already eliminated

All of the following have been verified OFF on the Cloudflare zone `ryanckelly.ca` (token in `/opt/foodlog/.env.diagnos`, zone id `8018b83de49668d5edbf0b4ce6193bea`, account id `8e80b7e9a30e365c6226e422a8edf800`):

- `minify` = `{css: off, html: off, js: off}`
- `rocket_loader` = off
- `mirage` = off
- `polish` = off
- `email_obfuscation` = off
- `server_side_exclude` = off
- `replace_insecure_js` = off
- `automatic_https_rewrites` = off
- `hotlink_protection` = off
- `always_online` = off
- `response_buffering` = off
- `prefetch_preload` = off
- **Bot Fight Mode** = off (checked in dashboard directly by user)
- **Development Mode** = on
- **Cache purged** (Purge Everything via dashboard, confirmed)
- **Container restarted** (`docker compose down && docker compose up -d`) — does not flush the stale response

No custom rulesets. Listed phases:
- `http_request_sanitize` (managed normalization)
- `http_request_firewall_managed` (managed free WAF)
- `ddos_l7` (managed DDoS)

No Workers deployed (our API token lacked account-scope to verify, but the Tunnel ingress config in `docker logs` is simply `{hostname: foodlog.ryanckelly.ca, service: http://localhost:3474}` with a `http_status:404` fallback — no path-based rules).

Full zone settings dump is at `/tmp/cf_settings.json` (from an earlier run; re-fetch with `bash /tmp/cf_probe.sh` if stale).

## Negative bisection results

- **Content rename**: `Movement & Recovery` → `Daily summary`, class `movement-section` → `fit-section`. Still stripped. So it's not the word "movement" triggering a filter.
- **Positional swap**: Moved Movement partial to the top of the response, before the meals section. Still stripped (along with a `<div>` appended after meals). So it's not "last section in the response."
- **Outer wrapper**: Wrapped whole `feed_partial.html` in a single `<div class="fl-feed-wrapper">…</div>`. Wrapper itself was stripped too. So it's not about the HTML being "unwrapped."
- **Separate endpoint**: Added `/dashboard/fit` that returns only the Movement partial. `/dashboard/fit` returns HTTP 404 when requested via the public URL but HTTP 200 via loopback. The 404 body is FastAPI's `{"detail":"Not Found"}` — but our app never logs the request (verified with unique query marker + `docker logs foodlog`). So the 404 is being **synthesized by CF** using the FastAPI format. `/dashboard/feed` on the same origin works fine, as does `/dashboard` and any path that existed previously.
- **Brand-new probe path**: Added `/dashboard/mv-probe-xyz` → initially returned 200 via CF, then subsequent requests started returning 404 too. New paths seem to fail after one hit. Extremely smells like negative-caching on the CF edge that `cf-cache-status: DYNAMIC` is lying about.

Key asymmetry: **paths that existed before any movement-section work (`/dashboard`, `/dashboard/feed`) pass through CF; new paths added during this debugging session (`/dashboard/fit`, `/dashboard/mv-probe-xyz`) return 404 from CF without reaching the origin.**

## What the backend actually does (for context)

- `foodlog/api/routers/dashboard.py` → `feed_partial()` is async, runs on-presence Google Health sync, builds a movement context dict from the local DB, and calls `TemplateResponse` with `Cache-Control: private, no-store, no-transform` in the response headers.
- `foodlog/templates/dashboard/feed_partial.html` includes `{% if include_movement %}{% include "dashboard/movement_partial.html" %}{% endif %}` at the end.
- `foodlog/templates/dashboard/movement_partial.html` renders `<section class="movement-section">` with sleep / workout / weight cards.
- Local DB currently holds 9 sleep rows (verified); `_build_movement_context()` returns a populated sleep view for today.

`Cache-Control: no-transform` on the response is **ignored by CF** (verified: the header is stripped from the CF-delivered response — the backend sends it but the public client never sees it). Content-Length from the backend (5939) is also removed; CF re-encodes with Brotli and sends chunked.

## Hypotheses worth testing

1. **Negative caching at a CF layer that `DYNAMIC` hides.** CF's docs claim DYNAMIC means not-cached, but the byte-identical responses strongly suggest otherwise. Possibly related to **Cache Reserve**, **Tiered Cache**, or **Cache Chaining** — features we don't have permission to inspect with our token. The user's plan is free tier.
2. **Something upstream of the tunnel doing path-based interception.** The fact that brand-new paths 404 from CF without reaching the origin suggests a Cloudflare-level allowlist or negative cache, not origin behavior.
3. **HTTP/2 continuation frame truncation at a specific stream boundary.** Unlikely given deterministic byte-identical truncation at a content boundary (always after a `</section>`), but worth ruling out via HTTP/1.1 or H3 forced.
4. **Some CF Pages / CF Access / CF Zaraz artifact on this zone.** User claims no custom config, but the token can't verify all surfaces. Running `cloudflared tunnel info <id>` or checking the **Cloudflare Zero Trust dashboard → Networks → Tunnels → foodlog** tunnel config directly might reveal a second ingress rule.
5. **Some state-changing prior request poisoned the CF edge cache** — e.g., a request that once returned an error now permanently returns 404 for new paths until an edge cycle. No API way to flush this we've found.

## Credentials available to the next agent

- `/opt/foodlog/.env.diagnos` — Cloudflare API token with Zone:Read, Zone:Zone Settings:Edit, Zone:Zone WAF:Edit on `ryanckelly.ca` only. (No Workers, no Cache Purge, no Bot Management scopes — user can add if needed.)
- `/tmp/cf_probe.sh`, `/tmp/cf_deep_probe.sh`, `/tmp/cf_disable_*.sh`, `/tmp/cf_purge.sh` — scripts we used; re-runnable.
- `/tmp/cf_settings.json`, `/tmp/cf_rulesets.json` — snapshots from earlier runs; may be stale.

## What to try first

1. **Read the last 20 commits on `main`** (`git log --oneline | head -20`) to see the Google Health integration work. The client at `foodlog/clients/google_health.py` was rewritten against the real v4 API response shape during this session; only `sleep` is fully parsed today. `steps`, `weight`, `total-calories`, `heart-rate`, `daily-resting-heart-rate`, `exercise` either return `{}` (no data in user's account) or 400 (filter-grammar issue for that type — see `FILTER_FIELDS` map). That's a known follow-up, unrelated to the CF issue.

2. **Add Cache Purge + Workers Read scopes to the token**, then re-run `cf_probe.sh` to inspect Cache Rules, Transform Rules, Workers routes. If any exist they'd explain everything. (Our current token's auth errors on those endpoints left that blind spot.)

3. **Bypass the tunnel with a test.** Temporarily toggle the DNS record to grey-cloud (DNS only) for `foodlog.ryanckelly.ca` and open the tunnel to the public IP directly — if the content appears, the issue is 100% inside Cloudflare's edge. (Requires user action in CF DNS tab and a reverse proxy since the tunnel itself goes away.)

4. **Try a completely different hostname** on the same zone — e.g., `foodlog2.ryanckelly.ca` via a separate CNAME/tunnel ingress. If `foodlog2` works and `foodlog` doesn't, something on the specific `foodlog` hostname is corrupt on the edge. Contact CF support with that evidence.

5. **Look at the FastAPI middleware stack** (`foodlog/api/app.py`, `foodlog/api/auth.py`) to confirm there's no middleware that varies output based on incoming headers — specifically `X-Forwarded-For`, `CF-Connecting-IP`, `X-Forwarded-Proto`. Earlier tests show the response size doesn't vary with Host header via raw socket tests, but the CF edge adds several other headers we haven't fully enumerated.

## Out of scope for this handoff

The Google Health API integration has other known-broken data types (steps, weight, workouts, etc.) — those are follow-ups, not the cause of the CF issue. Don't chase those unless asked; they're documented in `foodlog/clients/google_health.py`'s module docstring.
