# When You're Back — 4 Steps to Finish Deployment

All code tasks (1–10) are done and committed on branch `feat/tailscale-deploy`. Four manual steps remain.

## 1. Generate a Tailscale Auth Key

Go to <https://login.tailscale.com/admin/settings/keys> and click **Generate auth key**.

Settings:
- **Reusable:** ON
- **Ephemeral:** OFF
- **Pre-approved:** ON (if your tailnet uses device approval)
- **Expiration:** 90 days is fine
- Tags: none (unless you use ACL tags)

Copy the key (starts with `tskey-auth-`).

## 2. Add the Key to `.env`

Edit `/opt/foodlog/.env` — find the `TS_AUTHKEY=` line (currently empty) and paste your key after the `=`.

```bash
nano /opt/foodlog/.env
```

Make sure permissions are 600:
```bash
chmod 600 /opt/foodlog/.env
```

## 3. Deploy

```bash
cd /opt/foodlog
docker compose up -d
```

Wait ~15 seconds, then verify:

```bash
docker compose ps
# Both containers should be "running", foodlog-tailscale "healthy"

curl -s http://localhost:3473/health
# Expected: {"status":"ok","fatsecret":true,"usda":true}

docker exec foodlog-tailscale tailscale status
# Should show "foodlog" as Self with a 100.x.x.x IP

# Test MCP endpoint
curl -sL -X POST http://localhost:3473/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}' \
  | head -3
# Expected: SSE response with "protocolVersion":"2024-11-05"

# Verify today's logged meals survived the migration
curl -s "http://localhost:3473/summary/daily?date=$(date +%F)" | python3 -m json.tool
# Expected: Breakfast (325 kcal) + Lunch (736 kcal) totals
```

From **another tailnet device** (your phone, another laptop):

```
https://foodlog.tailf67313.ts.net:3473/health
```

Should return the same JSON.

## 4. Add to Claude Android

Open the Claude Android app → **Settings → Connectors → Add Custom MCP Server**

- Name: `FoodLog`
- URL: `https://foodlog.tailf67313.ts.net:3473/mcp`
- Auth: None (Tailscale is the auth)

Make sure Tailscale is active on your phone. Then in a new Claude conversation, ask: **"What did I eat today?"** — Claude should call `get_daily_summary` and show your logged meals.

---

## Then Finish the Branch

If everything works:

```bash
cd /opt/foodlog
git checkout master
git merge feat/tailscale-deploy
# Optional: git branch -d feat/tailscale-deploy
```

Claude Code will need a restart (fresh session) for the new HTTP-based MCP connection to pick up.

---

## What Got Built

| # | Task | Status |
|---|------|--------|
| 1 | Move `/home/ryan/foodlog` → `/opt/foodlog`, migrate DB | ✅ |
| 2 | Update config default DB path | ✅ |
| 3 | Add cached session factory helper | ✅ |
| 4 | Refactor MCP server — tools call services directly | ✅ |
| 5 | Mount MCP on FastAPI at `/mcp` with combined lifespan | ✅ |
| 6 | Switch `.mcp.json` + Claude Code registration to HTTP | ✅ |
| 7 | Create Dockerfile (tested: builds, starts, health OK) | ✅ |
| 8 | Create `docker-compose.yml` + `serve.json` | ✅ |
| 9 | Gitignore `data/` and `tailscale-state/` | ✅ |
| 10 | Deployment README at `doc/README.md` | ✅ |
| 11 | **Tailscale auth key** | 👤 Manual |
| 12 | **`docker compose up -d`** | 👤 Manual |
| 13 | **Smoke test** | 👤 Manual |
| 14 | **Claude Android connector** | 👤 Manual |

42 tests pass. 10 commits on `feat/tailscale-deploy` (vs master).

## Troubleshooting

**Claude Code says foodlog "Failed to connect"**: The API server needs to be running. `docker compose up -d` starts it. Check with `docker compose ps`.

**`/mcp` returns 307 redirect**: Some clients need `-L` to follow. Claude Code and the MCP SDK handle redirects natively, so this shouldn't be an issue in practice.

**FatSecret returns "Invalid IP address"**: The whitelist for your IP (`64.42.145.229`) was applied earlier in the session and took effect — should still work.

**Container won't start**: `docker logs foodlog --tail 30`. Most likely cause is a bad env var in `.env`.

**Tailscale won't connect**: `docker logs foodlog-tailscale --tail 30`. Most common is an expired/used auth key — generate a fresh one.

## Rollback

If deployment has issues and you want to revert to the old direct-python-run setup:

```bash
cd /opt/foodlog
docker compose down
source .venv/bin/activate
python -m foodlog.api.app
# And in another terminal, switch MCP back to stdio:
claude mcp remove foodlog --scope user
claude mcp add --scope user foodlog -- /opt/foodlog/.venv/bin/python /opt/foodlog/mcp_server/server.py
```

SQLite data survives — `data/foodlog.db` is untouched by `docker compose down`.
