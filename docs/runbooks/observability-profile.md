# Observability profile (optional)

> **Doc status:** Active

**Audience:** Unraid / Compose operators who want Prometheus later  
**Status:** Stub — **not required** for Oneirodex 1.0

## Default ops path (use this first)

Near-realtime operator visibility ships **in-app**:

| Surface | Purpose |
|---|---|
| `GET /pulse` | Liveness (process up) |
| `GET /awake` | Readiness (DB + startup init) — Compose / Unraid healthcheck |
| Admin → Ops (`/admin/ops`) | Polls `/admin/api/ops/summary` (~15s) including **Services** (LiveKit · malware/ClamAV · companions · queues · game_servers) — [ops-summary.md](../admin/ops-summary.md) |

Do **not** block upgrades or smoke sign-off on Prometheus/Grafana.

## Application logging

The backend configures stdlib `logging` at startup
(`oneirodex/utils/logging_setup.py`, called from `create_app()`): one console
handler on **stdout**, so `docker logs` / the Unraid container log show it.
Startup also forces the stdout/stderr streams to UTF-8 (`errors="replace"`) so a
log line with an emoji does not raise `UnicodeEncodeError` and vanish on a
Windows console running code page cp1252; Linux/Docker already run a UTF-8 locale
and are unaffected.

| Env var | Default | Effect |
|---|---|---|
| `ONEIRODEX_LOG_LEVEL` | `INFO` | `CRITICAL` / `ERROR` / `WARNING` / `INFO` / `DEBUG`. Anything else falls back to `INFO`. `werkzeug` stays at `INFO` even when this is `DEBUG`. |
| `ONEIRODEX_LOG_JSON` | unset (`0`) | `1` emits one JSON object per line (`ts`, `level`, `logger`, `msg`, `request_id`, and `method`/`path` in a request) for a log shipper. Unset keeps the human console format. |

Each log line carries a short `request_id` when emitted during a request, so a
household member's report ("it broke when I hit Scan") can be traced across
lines. The backend is mid-migration from `print()` to `logging`; a ratchet
(`scripts/print_lint.py`) keeps the remaining `print()` count from growing.

## Adding Prometheus later

Repo `docker-compose.yml` keeps a **commented** `# profile: observability` stub (no images pulled by default — avoids broken Compose when you only want `app` + `db`).

Typical operator steps when you opt in:

1. Uncomment (or copy) the stub services under the observability note in `docker-compose.yml`.
2. Point Prometheus at Oneirodex only after a scrape endpoint exists (future `/metrics` — admin or token-gated; never open library paths on an unauthenticated scrape).
3. Start with: `docker compose --profile observability up -d` (same pattern as `livekit` / `clamav`).
4. Keep Admin → Ops as the primary glance; treat Grafana as optional dashboards on top.

Until `/metrics` ships, scrape configs that assume it will fail — prefer health curls + Ops Services.

## Security notes

- Do not expose metrics without auth on a public bind.
- Prefer LAN-only scrape or a reverse-proxy ACL.
- No Discord / webhook alert sinks — use in-app SystemEvents / optional SMTP digest.

## Related

- [ops-summary.md](../admin/ops-summary.md) — `services` key contract  
- [docker-compose-deploy.md](docker-compose-deploy.md)  
- [unraid-deploy.md](unraid-deploy.md)
