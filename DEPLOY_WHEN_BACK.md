# When You're Back - Cloudflare OAuth Deployment

The Tailscale deployment has been superseded. FoodLog now deploys as one
container that runs the FastAPI/MCP app plus `cloudflared`.

## 1. Create Cloudflare Tunnel

Cloudflare Zero Trust -> Networks -> Tunnels -> Create tunnel:

- Name: `foodlog`
- Connector type: `cloudflared`
- Public hostname: `foodlog.ryanckelly.ca`
- Service: `http://localhost:3474`

Copy the tunnel token. It starts with `eyJ...`.

## 2. Add Secrets to `.env`

```bash
cd /opt/foodlog
openssl rand -hex 32
nano /opt/foodlog/.env
chmod 600 /opt/foodlog/.env
```

Required values:

```env
FOODLOG_PUBLIC_BASE_URL=https://foodlog.ryanckelly.ca
FOODLOG_OAUTH_LOGIN_SECRET=<openssl rand -hex 32 output>
CLOUDFLARE_TUNNEL_TOKEN=<Cloudflare tunnel token>
```

## 3. Deploy

```bash
cd /opt/foodlog
docker compose up -d --build
docker compose ps
docker logs foodlog --tail 50
curl -s https://foodlog.ryanckelly.ca/healthz
```

Expected health response:

```json
{"status":"ok"}
```

Unauthenticated MCP should return OAuth challenge headers:

```bash
curl -i -s -X POST https://foodlog.ryanckelly.ca/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  | head -20
```

Expected: `401` and `WWW-Authenticate` with `resource_metadata`.

## 4. Add Connector in Claude Web

Open https://claude.ai -> Settings -> Connectors -> Add custom connector:

- Name: `FoodLog`
- URL: `https://foodlog.ryanckelly.ca/mcp`

Complete the OAuth flow. When FoodLog asks for the secret, paste
`FOODLOG_OAUTH_LOGIN_SECRET`.

After that, Claude Android can use the connector from your Claude account.

## Troubleshooting

- Tunnel not connected: `docker logs foodlog --tail 100` and check Cloudflare token.
- OAuth fails before consent: verify `FOODLOG_PUBLIC_BASE_URL` matches the public hostname.
- Consent rejects secret: verify `.env` has the exact `FOODLOG_OAUTH_LOGIN_SECRET`.
- Reconnect needed: use Claude web or Claude Desktop, then Android will use the refreshed connector.

## Rollback

```bash
cd /opt/foodlog
docker compose down
git checkout <previous-working-commit>
docker compose up -d --build
```

SQLite data remains in `/opt/foodlog/data/foodlog.db`.
