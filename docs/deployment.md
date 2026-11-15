# Deploying MCP Guardian on a VPS

One server runs two containers: the app (web app, API and the ten DVMCP lab servers) and Caddy, which serves
HTTPS. Written for `careeristpro.cloud` on a Hostinger KVM VPS (Ubuntu); any Docker host works the same way.

## 1. DNS
In the domain's DNS zone (Hostinger: hPanel, Domains, DNS / Nameservers) add:

| Type | Name | Value |
|---|---|---|
| A | `@` | the VPS's public IPv4 address |
| A | `www` | the same address |

Remove any other A or AAAA record for `@` (for example the one pointing at Hostinger's web hosting). Check with
`nslookup careeristpro.cloud`; it must return the VPS address before the first start, or Caddy cannot get a certificate.

## 2. The server
```bash
ssh root@<vps-ip>
apt-get update && apt-get -y upgrade
# firewall: SSH, HTTP, HTTPS only. The lab servers are deliberately vulnerable and must never be reachable.
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
# Docker (skip if `docker compose version` already works)
curl -fsSL https://get.docker.com | sh
```
Docker publishes ports by editing the firewall itself, so `ufw` alone does not hide a published port. This setup publishes
only Caddy's 80 and 443; do not add `ports:` to the `app` service.

## 3. The code and the keys
```bash
git clone https://github.com/YugenJarwal13/MCPGuardian.git && cd MCPGuardian
cp deploy/server.env.example deploy/server.env
nano deploy/server.env        # OPENROUTER_API_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
```

## 4. Start
```bash
docker compose -f deploy/docker-compose.yml --env-file deploy/server.env up -d --build
docker compose -f deploy/docker-compose.yml logs -f app      # wait for "DVMCP lab: 10/10 servers up"
```
The first build takes a few minutes. Caddy requests the certificate on the first visit to `https://careeristpro.cloud`.

## 5. Check
- `https://careeristpro.cloud/health` returns JSON with `"ok": true`.
- Live demo: the ten DVMCP cards show "running"; run one.
- Check a server: run it on a public MCP URL; for an OAuth server, approve on the provider's page.
- Langfuse shows a new trace with environment `production`.

## Operations
| Task | Command |
|---|---|
| Update to the latest code | `git pull && docker compose -f deploy/docker-compose.yml --env-file deploy/server.env up -d --build` |
| Logs | `docker compose -f deploy/docker-compose.yml logs -f app` |
| Restart | `docker compose -f deploy/docker-compose.yml restart app` |
| Stop | `docker compose -f deploy/docker-compose.yml down` (volumes, and so the history and certificates, are kept) |
| Memory | `docker stats --no-stream` |

State (fingerprints, case history, model answer cache) lives in the `guardian-state` volume, certificates in `caddy-data`.

## Notes
- The free model's daily quota (about 50 requests) is shared by every visitor; `GUARDIAN_LLM_RUNS_PER_DAY` caps the site.
- Public mode is on in the image: internal addresses are refused, runs are rate-limited, and the DVMCP challenges that execute
  commands or read files are inspect-only.
- OAuth sign-in needs `GUARDIAN_PUBLIC_URL`; compose sets it to `https://$GUARDIAN_DOMAIN`.
