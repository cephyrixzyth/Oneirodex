# OIDC / SSO Runbook (Oneirodex)

Oneirodex supports OpenID Connect (OIDC) single sign-on with identity providers such as **Authentik**, **Authelia**, and **Keycloak**. Local username/password login remains available when SSO is enabled.

**Unraid + Authentik walkthrough:** [oidc-authentik-unraid.md](oidc-authentik-unraid.md)

## Feature flag

SSO is **disabled by default**. Both must be true:

1. Environment: `OIDC_ENABLED=true`
2. Admin UI: **Integrations → OIDC / SSO → Enable OIDC SSO**

Restart the application after changing environment variables.

## Environment variables

Copy from `.env.example`:

| Variable | Description |
|----------|-------------|
| `OIDC_ENABLED` | Master env switch (`true` / `false`) |
| `OIDC_ISSUER_URL` | IdP issuer base URL (e.g. `https://auth.example.com/application/o/oneirodex/`) |
| `OIDC_CLIENT_ID` | OAuth client ID |
| `OIDC_CLIENT_SECRET` | Client secret (optional for public PKCE clients) |
| `OIDC_REDIRECT_URI` | Must match IdP registration exactly, e.g. `https://oneirodex.example.com/login/oidc/callback` |
| `OIDC_SCOPES` | Default: `openid email profile` |
| `OIDC_ROLE_CLAIM` | Claim used for role mapping (default: `groups`) |
| `OIDC_ROLE_MAP` | JSON object mapping IdP claim values → Oneirodex roles |
| `OIDC_DISPLAY_NAME` | Login button label (default: `Sign in with SSO`) |
| `TRUSTED_PROXIES` | Number of trusted reverse-proxy hops (`0` = off, `1` = typical single nginx/Caddy/Traefik) |
| `SESSION_COOKIE_SECURE` | `true` behind HTTPS (default); `false` for local HTTP dev only |
| `REMEMBER_COOKIE_SECURE` | Same as above for remember-me cookies |

Admin settings stored in `global_settings` override env defaults when set.

## Authentik checklist (production)

Use this sequence when wiring Oneirodex to a live Authentik instance. No secrets belong in git — configure credentials only in `.env` or your secret store.

### 1. Create the OAuth2/OIDC provider (Authentik admin)

1. **Applications → Providers → Create** → choose **OAuth2/OpenID Provider**.
2. **Name:** `Oneirodex` (or your convention).
3. **Authorization flow:** pick a flow that authenticates users (e.g. default authentication flow).
4. **Client type:** **Confidential** if you set `OIDC_CLIENT_SECRET`; **Public** if using PKCE-only (Oneirodex sends PKCE either way).
5. **Redirect URIs/Origins (regex):** add exactly:
   ```
   https://<oneirodex-public-host>/login/oidc/callback
   ```
   Must match `OIDC_REDIRECT_URI` character-for-character (scheme, host, path, no trailing slash unless registered).
6. **Signing key:** use Authentik default or your org key.
7. Save the provider and note the **Client ID** and **Client Secret** (confidential clients only).

### 2. Create the Authentik application

1. **Applications → Applications → Create**.
2. Link the provider from step 1.
3. **Slug** becomes part of the issuer URL: `https://<authentik-host>/application/o/<slug>/`.
4. Set **Launch URL** to your public Oneirodex URL (optional; helps admin UX).

### 3. Copy issuer URL and credentials into Oneirodex

In `.env` (or deployment secrets):

```env
OIDC_ENABLED=true
OIDC_ISSUER_URL=https://auth.example.com/application/o/oneirodex/
OIDC_CLIENT_ID=<from Authentik provider>
OIDC_CLIENT_SECRET=<from Authentik provider, or empty for public client>
OIDC_REDIRECT_URI=https://oneirodex.example.com/login/oidc/callback
OIDC_SCOPES=openid email profile
OIDC_ROLE_CLAIM=groups
TRUSTED_PROXIES=1
SESSION_COOKIE_SECURE=true
REMEMBER_COOKIE_SECURE=true
```

Restart Oneirodex after env changes.

### 4. Enable the admin toggle (second flag)

1. Log in as a local admin.
2. **Admin → Integrations → OIDC / SSO**.
3. Enable **Enable OIDC SSO** and confirm issuer, client ID, redirect URI, scopes, and role claim match Authentik.
4. Set **Site URL** (`site_url`) to the public HTTPS base URL, e.g. `https://oneirodex.example.com`.

Both `OIDC_ENABLED=true` **and** the admin toggle must be on before the SSO button appears.

### 5. Groups → Oneirodex roles

1. In Authentik, create groups that match your role map keys, e.g. `oneirodex-admin` / `oneirodex-admin`, `oneirodex-librarian` / `oneirodex-librarian`, `oneirodex-child` / `oneirodex-child`.
2. Assign users to groups.
3. Ensure the **groups** claim (or your chosen `OIDC_ROLE_CLAIM`) is included in the ID token / userinfo. With Authentik, this usually requires a **Property Mapping** or scope that exposes group membership to the OAuth app.
4. Configure `OIDC_ROLE_MAP` (env or admin UI), default shape:

```json
{
  "admin": "admin",
  "oneirodex-admin": "admin",
  "oneirodex-admin": "admin",
  "librarian": "librarian",
  "oneirodex-librarian": "librarian",
  "oneirodex-librarian": "librarian",
  "child": "child",
  "oneirodex-child": "child",
  "oneirodex-child": "child"
}
```

Unmapped users JIT-provision with role `user`. Linking: an existing local account is linked on first sign-in only when the provider marks its **email as verified** (`email_verified: true`); after that the account follows the provider's `sub`. Usernames never link accounts, and the local email is never overwritten.

### 6. Reverse proxy and HTTPS

1. Terminate TLS at nginx, Caddy, or Traefik.
2. Forward headers to Oneirodex:

```nginx
location / {
    proxy_pass http://127.0.0.1:5006;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

3. Set `TRUSTED_PROXIES=1` so Flask honors `X-Forwarded-Proto` / `X-Forwarded-Host` for OIDC redirects and `_external=True` URLs.
4. Keep `SESSION_COOKIE_SECURE=true` when users reach the site over HTTPS.

### 7. Smoke test (no IdP secrets in repo)

Run unit tests locally (no live Authentik required):

```bash
pytest tests/test_oidc_unit.py -q
```

Manual smoke checklist after deploy:

- [ ] `/login` shows **Sign in with SSO** when both enable flags are on.
- [ ] Click SSO → browser redirects to Authentik (HTTPS URL, correct client).
- [ ] After login → redirect to `https://<host>/login/oidc/callback` (not `http://127.0.0.1:5006/...`).
- [ ] User lands on Discover; session persists on refresh.
- [ ] User in `oneirodex-admin` or `oneirodex-admin` group receives `admin` role in Oneirodex.
- [ ] Wrong redirect URI → flash mentions redirect URI mismatch (check admin + Authentik provider).
- [ ] Set `OIDC_ENABLED=false` or disable admin toggle → SSO button hidden; local login still works.

## IdP setup (Authelia / Keycloak)

Same general requirements as Authentik:

1. Create an OAuth2/OIDC **confidential** or **public** client.
2. Grant type: **Authorization Code**.
3. Enable **PKCE (S256)**.
4. Redirect URI: `https://<oneirodex-host>/login/oidc/callback`
5. Scopes: `openid`, `email`, `profile`, plus any claim scope needed for groups/roles.
6. Ensure the IdP returns `sub`, `email` with `email_verified`, and `preferred_username`.

### Role mapping

Default JSON role map (also configurable in admin):

```json
{
  "admin": "admin",
  "oneirodex-admin": "admin",
  "oneirodex-admin": "admin",
  "librarian": "librarian",
  "oneirodex-librarian": "librarian",
  "oneirodex-librarian": "librarian",
  "child": "child",
  "oneirodex-child": "child",
  "oneirodex-child": "child"
}
```

JIT provisioning creates users with role `user` unless a mapped claim is present. Linking: an existing local account is linked on first sign-in only when the provider marks its **email as verified** (`email_verified: true`); after that the account follows the provider's `sub`. Usernames never link accounts, and the local email is never overwritten. If a provider does not send `email_verified`, an existing account with that email is **refused** at SSO sign-in ("An account with this email already exists") rather than linked or duplicated. Fix it at the provider (send `email_verified: true`), or, if the provider's admins (not its users) set every address, set `OIDC_TRUST_PROVIDER_EMAIL=true`. Accounts created by SSO without any email link by name.

## Flow

1. User clicks **Sign in with SSO** on `/login`.
2. Oneirodex redirects to IdP with authorization code + PKCE.
3. IdP redirects to `/login/oidc/callback` with `code` and `state`.
4. Oneirodex exchanges code, reads claims, JIT-provisions user, establishes Flask-Login session.
5. User lands on Discover (or `next` URL if safe).

## Troubleshooting

| Symptom | Check |
|---------|--------|
| No SSO button | `OIDC_ENABLED=true` **and** admin toggle enabled; restart after env change |
| Redirect URI mismatch | IdP client redirect must match `OIDC_REDIRECT_URI` exactly |
| Callback uses `http://` behind TLS | Set `TRUSTED_PROXIES=1`; proxy must send `X-Forwarded-Proto: https` |
| 503 on SSO click | Install `authlib` (`pip install authlib`) and restart |
| Login succeeds but instant logout | `SESSION_COOKIE_SECURE` vs HTTP; fix proxy or cookie settings |
| Wrong role | `OIDC_ROLE_CLAIM` and `OIDC_ROLE_MAP`; verify IdP group claims in token/userinfo |
| SSO session expired flash | User took too long or retried callback; start SSO again from `/login` |

## Tests

```bash
pytest tests/test_oidc_unit.py -q
```

Unit tests cover enable-flag logic, claim→role mapping, proxy hop parsing, and callback error messages without a live IdP.
