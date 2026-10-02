# Thin client

> **Doc status:** Active

Connect-only shell for browse / social / Big Picture — **not** Download · Install · Play. Windows, macOS and Linux.

## When to use it

| Seat | Use |
|---|---|
| **Thin** | Lounge laptop, social-only PC, kids machine that should never hold install ACLs |
| **Full companion** | The PC that downloads, extracts, and launches DRM-free titles — [desktop-companion.md](desktop-companion.md) |

Thin has **no** local install pipeline. Install/Update stay on the full companion (or browser download + companion extract).

## No binary: install the web app instead (TC-2b)

A Chromebook, a locked-down work laptop, a tablet or a headset cannot run an
unsigned Tauri build — and does not need to. **Preferences → Install this
library** installs the member app itself: its own window, its own icon, opening
straight on your shelf.

- **Chrome / Edge / Brave / Quest browser:** the Install button appears in
  Preferences, or use the install icon in the address bar.
- **Safari (iPad, iPhone, Mac):** Share → **Add to Home Screen**. Safari has no
  install prompt to offer, so Preferences shows the instruction rather than a
  button that cannot work.
- **Firefox desktop:** no install path; use a normal window or a pinned tab.

**This needs HTTPS.** Installing requires a service worker, browsers only allow
those on a secure origin, and a LAN address over plain HTTP is not one. If the
install row never appears, that is almost always why — see
the HTTPS section of [unraid-deploy.md](../runbooks/unraid-deploy.md#https-smtp-passkeys-hellfirenas) if you have
not set up TLS yet.

**What an installed copy keeps on the device:** the app's own code, fonts and
theme files. **Not** games, **not** cover art, **not** anything from the API.
That is deliberate — an installed app on a shared machine outlives a sign-out,
and one member's shelf should never be sitting in another member's browser
storage. Offline, the window shows a "no route to your library" page rather
than a stale one; signing out clears what little is cached.

An installed seat is still a *browser* seat: it heartbeats as `browser`, not as
`thin`, so it has no install ACLs to lose. If you want the seat to show up in
the operator's device list as a thin client, use the shell below.

## Build (unsigned)

```bash
cd clients/desktop
npm install
npm run tauri:build:thin
```

Produces an unsigned **OneirodexThin** installer via `tauri.thin.conf.json` (capabilities: `thin-main` / `thin-library` / `social` only) — `.exe` on Windows, `.dmg` on macOS, `.deb` / `.AppImage` on Linux. The full companion bundles as `Oneirodex`, so the two no longer overwrite each other. Details: [desktop-code-signing.md](../runbooks/desktop-code-signing.md) · all platforms at once: [local-installers.md](../runbooks/local-installers.md).

## Connect

1. **Account → API tokens** → create with the **Thin client** preset (`read:library` + `read:social` + `write:presence`; **no** `write:download`).
2. Copy the one-time secret with **Copy secret** (or select the secret field). Format is `gt_<prefix>_<urlsafe-secret>` — **hyphens and underscores in the secret are normal**. Paste the **entire** string; truncating after a `-` always fails auth.
3. Enter Oneirodex base URL. Optional API token uses the same paste normalize / shape checks as the full companion. **Save** stores URL + token; **Validate token** runs the collections check (same as companion Connect).
4. Open library / Friends only — lifecycle CTAs are out of scope.

Token lives in the OS credential store under the thin app's own service (`com.oneirodex.thin`), not plaintext `config.json` — so installing thin next to the full companion no longer overwrites the companion's token. Credential-store failures surface in status (not opaque “Bad data”).

## What this seat will not offer

The library says so instead of failing: Download / Install / Update / Uninstall on the action bar and in Big Picture, *Apply with companion* on versions, translations and extras, the Updates page's apply, and *Open in file explorer* (it copies the path instead). Play via Moonlight stays — streaming is not a local install. The Ways-to-play companion card says the launch happens on the companion, not here.

## Presence

With a token saved, the thin shell heartbeats as `device_kind=thin`, so the seat appears in the operator's device list (Admin → Ops → Companions → Devices) as a thin client rather than passing for a companion. It is never sent install/update commands: the server gates that on a companion seat **and** a download scope, and the thin preset has neither.

No token? Presence stays quiet and the library / Friends windows fall back to site login — everything else still works.

## What the library window looks like

The thin shell opens the member app marked as a thin seat, so Game details shows one honest line — *“Browse & social seat — download, install and update happen on the desktop companion”* — instead of Download / Install / Update / Uninstall buttons that this seat can never complete. Moonlight streaming stays available; it is not a local install.

## Honesty

- **Unsigned only** — no code-signing cert on any platform.
- Thin ≠ Android APK. Phone/tablet / Quest sideload is a future spike only.
- Headset `/vr` is browse-first (SteamVR / PSVR2 on the PC; Quest = friend PWA) — [controllers-and-vr.md](controllers-and-vr.md).
