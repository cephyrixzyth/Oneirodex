# Login rate limiting (proxy + app)

Oneirodex already rate-limits `/login` and password-reset in-process when `ENABLE_LOGIN_RATE_LIMIT=true` (default). That protects a **single worker**. Behind multiple Gunicorn/uWSGI workers or a reverse proxy, add a **proxy** limit so shared IPs cannot fan out across workers.

## App-level (already on)

| Setting | Notes |
|---|---|
| `ENABLE_LOGIN_RATE_LIMIT` | Default `true` — see `.env.example` |
| Keys | Per IP + username and per IP alone |
| Client IP | The connection's address. A client-sent `X-Forwarded-For` is ignored, because anyone can set it. Behind a reverse proxy, set `TRUSTED_PROXIES` to the number of proxies in front of Oneirodex; the app then takes the client address from the hops those proxies added. Without it, every visitor shares the proxy's address and one bucket. |
| Scope | In-memory per process — not shared across replicas |

Disable only for local debugging. Keep it on in production even with proxy limits.

## Proxy (recommended for O8)

Put a short burst limit on `POST /login` (and optionally password-reset) in Nginx, Caddy, Traefik, or Cloudflare.

### Nginx example

```nginx
limit_req_zone $binary_remote_addr zone=gt_login:10m rate=5r/m;

server {
  location = /login {
    limit_req zone=gt_login burst=10 nodelay;
    proxy_pass http://oneirodex_upstream;
  }
}
```

### Caddy example

```caddy
@login method POST path /login
rate_limit @login {
  zone login
  key {remote_host}
  events 5
  window 1m
}
```

### Cloudflare / Unraid reverse proxy

Use a WAF or rate-limit rule for path `/login` (and `/reset` / forgot-password if exposed) — e.g. 5–10 requests/minute per IP.

## Verify

1. With app limit on: repeated bad passwords return a rate-limit message (see `tests/test_login_rate_limit.py`).
2. With proxy limit: confirm `429` / challenge before hitting the app under a multi-worker soak.
3. Legitimate users behind NAT: raise burst slightly; never disable both layers.

Related: [settings-modules.md](../admin/settings-modules.md) · [privacy-data-handling.md](../admin/privacy-data-handling.md)
