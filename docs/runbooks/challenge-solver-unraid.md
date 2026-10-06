# Challenge solver (TRAWL) on Unraid / Compose (CH-2 / CH-6)

> **Doc status:** Active

Optional BYO browser/captcha solver for household acquire (Prowlarr / Jackett / debrid HTTP). **Off by default** — enable only when indexers return Cloudflare or captcha challenge pages.

## Security stance

| Rule | Why |
|---|---|
| **Never** publish TRAWL API (8191) or MITM proxy (8192) to the public internet | Solver + MITM CA can impersonate HTTPS on your LAN |
| Compose profile binds **no host ports** — app reaches TRAWL at `http://trawl:8191` on the Docker network | Same pattern as ClamAV TCP inside Compose |
| MITM proxy stays **off** unless you explicitly opt in | Installing TRAWL's CA in a trust store grants full TLS impersonation |
| Child accounts never configure the solver | Admin infrastructure only |

---

## Compose profile `challenge`

Repo `docker-compose.yml` adds Redis + [TRAWL](https://github.com/germondai/trawl) (`ghcr.io/germondai/trawl`) under profile **`challenge`** (not `trawl`).

```bash
# From repo root — .env must include SECRET_KEY + game paths
export ENABLE_CHALLENGE_SOLVER=true
export CHALLENGE_SOLVER_URL=http://trawl:8191
export CHALLENGE_SOLVER_MAX_TIER=5          # default; admin may raise in UI later
export ALLOW_PRIVATE_LAN_URLS=true          # required on Unraid for RFC1918 solver URL

docker compose --profile challenge up -d
```

Restart the app container after changing solver env so flags reload:

```bash
docker compose up -d app
```

### Image tag: `:latest` vs `:baseline`

| Tag | Use when |
|---|---|
| `ghcr.io/germondai/trawl:latest` (default) | Modern amd64/arm64, kernel 5.1+ |
| `ghcr.io/germondai/trawl:baseline` | Older NAS CPUs (no AVX2), Synology DSM / kernel 4.4, Atom-era Unraid |

Set in `.env` before `up`:

```bash
TRAWL_IMAGE=ghcr.io/germondai/trawl:baseline
```

Baseline is slightly slower but avoids Bun runtime crashes on older kernels.

---

## Unraid Community Apps / standalone Docker install

The Unraid host in this deployment is a Celeron J4125 without AVX2. Use the upstream
`1.7.0-baseline` image; it is built for J4125-class CPUs. Keep TRAWL on the existing
`oneirodex-net` network, publish no ports, and use a dedicated Redis instance so the
existing household Redis service remains isolated. The commands below create the Redis
data volume once and start both containers with restart policies:

```bash
docker volume create oneirodex-challenge-redis-data
docker run -d --name oneirodex-challenge-redis \
  --restart unless-stopped --network oneirodex-net \
  -v oneirodex-challenge-redis-data:/data \
  redis:8.10.2-alpine

docker run -d --name oneirodex-trawl --network oneirodex-net \
  --network-alias trawl --restart unless-stopped --shm-size=1g \
  --memory=1536m --memory-swap=1536m \
  -e REDIS_URL=redis://oneirodex-challenge-redis:6379 \
  -e BROWSER_POOL_SIZE=1 \
  ghcr.io/germondai/trawl:1.7.0-baseline
```

Neither container has a host port mapping. Confirm TRAWL's `/health` reports healthy and
inspect its memory diagnostics after the browser pool warms. Do not enable its MITM proxy
or install a TRAWL CA certificate. With Oneirodex's solver flag left off, the sidecar is
idle and does not alter acquisition behavior. Enabling it requires both
`ENABLE_CHALLENGE_SOLVER=true` and `ALLOW_PRIVATE_LAN_URLS=true`; that second setting
widens which private-network endpoints the app may contact, so enable it only when the
admin intends to use TRAWL.

To remove the optional services later, stop/remove the two containers. Keep
`oneirodex-challenge-redis-data` until its cached session data is no longer needed.

---

## Enable in Oneirodex

1. Start profile **`challenge`** (above).
2. In `.env` (or Unraid Compose env file):

   ```bash
   ENABLE_CHALLENGE_SOLVER=true
   CHALLENGE_SOLVER_URL=http://trawl:8191
   CHALLENGE_SOLVER_PROVIDER=flaresolverr_compat   # or trawl for /scrape (CH-3+)
   CHALLENGE_SOLVER_TIMEOUT_MS=60000
   CHALLENGE_SOLVER_MAX_TIER=5
   ALLOW_PRIVATE_LAN_URLS=true
   ```

3. Recreate app: `docker compose up -d app`.
4. When CH-5 ships: Admin → Features → **Test** + Ops health chip.

With `ENABLE_CHALLENGE_SOLVER=false` (default), acquire behavior is unchanged even if TRAWL is running.

---

## Prowlarr URL parity

If Prowlarr already uses FlareSolverr / TRAWL:

- Prowlarr → Settings → Indexers → FlareSolverr URL: often `http://host:8191` from Prowlarr's network namespace.
- Oneirodex (inside Compose) uses the **service name**: `http://trawl:8191` — not `localhost`.
- Same sidecar can serve both when TRAWL is on the shared Compose network; do not duplicate solvers unless you isolate networks.

External solver (already on LAN): set `CHALLENGE_SOLVER_URL=http://192.168.x.x:8191` and keep `ALLOW_PRIVATE_LAN_URLS=true`.

---

## Smoke test

1. TRAWL health (from app container or any container on the Compose network):

   ```bash
   docker compose exec app curl -sf http://trawl:8191/health
   ```

2. With flag on, challenged indexer search should retry once through the solver (CH-3+).
3. Confirm **no** host firewall rule exposes 8191/8192 — `docker compose ps` should show TRAWL without `0.0.0.0:8191->8191/tcp`.

---

## MITM forward proxy (CH-6 — advanced, docs-only caution)

TRAWL can run an HTTP **MITM forward proxy** on port **8192** when `TRAWL_MITM_PROXY_ENABLED=true`. Some indexers need connection-bound clearance cookies that FlareSolverr `/v1` cannot hand off to Prowlarr's own HTTP client.

### CA warning

Enabling MITM generates a **custom root CA**. Any client that trusts it (system keychain, Java `cacerts`, Prowlarr JVM) will accept TLS certificates minted by TRAWL for **any** HTTPS host the proxy sees.

| Do | Don't |
|---|---|
| Use only on trusted household LAN / Docker network | Publish 8192 on WAN or reverse proxy |
| Install CA only on machines that need the proxy | Install CA on shared/public PCs |
| Rotate/revoke CA if the volume is compromised | Treat MITM as "just another port forward" |

Fetch CA (LAN only, from a container on the network):

```bash
docker compose exec app curl -sf http://trawl:8191/proxy-ca.crt -o trawl-proxy-ca.crt
```

Install per OS/browser docs, then point Prowlarr/qBit **only** at `http://trawl:8192` as HTTP proxy when MITM is enabled. Oneirodex Compose **does not** publish 8192 to the host — configure proxy clients inside Compose or via internal DNS.

Default Compose keeps `TRAWL_MITM_PROXY_ENABLED=false`.

---

## Unraid Compose Manager

1. Indirect Compose File: `/mnt/user/example-share/_projects/Oneirodex/docker-compose.yml`
2. External ENV File: `/mnt/user/example-share/_projects/Oneirodex/.env`
3. Add profile in stack UI or run once from terminal:

   ```bash
   cd /mnt/user/example-share/_projects/Oneirodex
   docker compose --profile challenge up -d
   ```

4. Old NAS: add `TRAWL_IMAGE=ghcr.io/germondai/trawl:baseline` to `.env`.
5. Do **not** add custom port mappings for TRAWL in Unraid UI.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| TRAWL exits on start (Synology / J4125) | Switch to `:baseline`; pull fresh image (no stale cache) |
| App "solver unreachable" | Profile `challenge` up? URL `http://trawl:8191`? `ALLOW_PRIVATE_LAN_URLS=true`? |
| Search still shows challenge HTML | `ENABLE_CHALLENGE_SOLVER=true`? CH-3 wiring shipped? Prowlarr may need its own FlareSolverr URL |
| Timeouts | Raise `CHALLENGE_SOLVER_TIMEOUT_MS`; check TRAWL logs; tier 4 residential is operator-owned cost/ToS |

Related: [docker-compose-deploy.md](docker-compose-deploy.md) · [admin/troubleshooting.md](../admin/troubleshooting.md) (CH-5).
