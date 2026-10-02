# Getting started (web)

> **Doc status:** Active

Oneirodex is a self-hosted multi-user game library. Members browse and download DRM-free titles your admin has scanned.

**Defaults (operators):** Most product modules ship **on** (`ENABLE_*` in `.env.example`). **OIDC / SSO stays off** until you set `OIDC_ENABLED=true` and enable it under Admin → Integrations. Optional ClamAV: `docker compose --profile clamav up -d` when you want daemon scans in addition to filename heuristics — [settings-modules.md](../admin/settings-modules.md).

## Sign in

1. Open the server URL (default port **5006**).
2. Sign in with the account your admin invited, or local credentials from first-run setup.
3. Optional SSO (Authentik/OIDC) if the admin enabled it — same login page when configured.

## Member chrome

After login you land in the **member SPA**: a **left rail** of destinations and a slim **top bar**
for whatever the page you are on can do.

The rail is grouped, and every group folds away — including **Oneirodex**, which holds the five
core destinations:

| Group | Destinations |
|---|---|
| **Oneirodex** | Discover · Game Catalog · Systems · Downloads · Favorites |
| Game Catalog | Collections · Wishlist · Updates · Acquire · Ownership · Release calendar |
| Social | Friends (dock) · Chat (slide-out) · Notifications · Activity · News |
| Play | Big Picture · Playtime · VR · Trailers |
| Support | Report · Help |
| Manage | Admins only — opens the admin shell |

Which groups you have folded is remembered between sessions. Collapsing the whole rail to icons
leaves every group open, because a folded group in an icons-only rail would be destinations that
vanished with no visible way back.

Rail details worth knowing:

- The **logo** is large at the top of the expanded rail. Destination **icons and labels are small**, so the column is a list of names rather than a stack of marks.
- Each icon **animates in its own way** on hover — the heart beats, the download arrow falls, the
  calendar page turns, the refresh mark spins — so motion tells you *which* row you found, not
  merely that you found one. All of it is suppressed under OS reduced-motion.
- The section you are in takes your **theme's accent colour**, icon and label together, so "where I
  am" looks different from "where the pointer is".

The **top bar** carries, left to right: the rail toggle and **Filters** as adjacent chromeless
controls (no shared outline), the page's own view switcher, the tile-size slider, a count, and your
account.

**Profile / account** is the button at the right of the top bar. It shows **your name and your
chosen avatar** rather than a generic person glyph, and opens the account menu (not a full-page
takeover). Choosing **Profile**, **Change avatar**, **Change password**, **Invites** or **API tokens** opens the **account modal** over the page you were on, styled like the game preview popup, with a strip along the top to move between the five panels without closing. Nothing navigates away, so your scroll position and filters survive. The old `/settings_*` and `/user/invites` pages still work if you open them directly — they are the fallback for Big Picture and for a browser with JavaScript off.

**Friends** in the rail opens the stay-open Friends dock in place — it does **not** navigate to `/social-companion` as the main SPA shell.

**Loading looks the same everywhere.** Every page, panel and modal that is fetching something shows
the same animated loading motif and the same **Try again** on failure — Discover and its "see all"
row pages included. If a page shows you a bare sentence where a loading motif should be, that is a
bug worth reporting.

### Inviting someone

Account menu → **Profile → Invites**. Enter an email address to have the server send the invite, or **leave it blank** to get a link you can pass on however you like — a chat message, a note, reading it out. The link is the invite either way; email is only one way of delivering it, so a household with no mail server can still add members. Links last 48 hours and count against your invite quota until used or revoked.

If you are an admin and the new member has no email at all — a child's console login, the living-room account — **Admin → Invites → Add member without email** creates the account directly with a username and password you choose.

**Keyboard:** Tab to **Skip to main content** (first focusable control) to jump past the top nav into `#main-content`. Top nav and the **Ctrl/Cmd+K** command palette show a visible focus ring on keyboard focus. On long scrollable pages, **Jump to top** / **Jump to bottom** controls appear bottom-left (hide when the page doesn’t scroll).

**Command palette:** press **Ctrl+K** (⌘K on Mac) or the top-nav **Search** hint to jump to any primary/More page, Preferences, Admin, or Help. On **Game Catalog**, Ctrl+K searches **library titles** first. Screenshot backlog for palette / Ops / health probes: [CAPTURE.md](../assets/readme/CAPTURE.md).

Game Catalog **page size** options go up through **200–1000** (full allowlist 20/50/100/200/250/300/400/500/1000) — [preferences-themes.md](preferences-themes.md). Game Catalog Filters include **Signals** chips (UPDATE · MISSING · NEW · LANG). Filters open from a **Filters** button on the catalog bar.

**Discover shelves** can be pinned or hidden per account (**Rows** in the top bar) — the buttons take effect immediately. News **See all** opens the News page. A shelf with nothing honest to show is hidden rather than padded. **Game Catalog** shows one tile per title, not per copy — Preview → Available on lists the other systems. A grey Play button still opens and explains why.

If Discover/Game Catalog look unstyled, the deploy is missing **`member-app.css`** — ask an admin to rebuild the image.

On phones and narrow tablets (≤900px), the top nav becomes a **hamburger** menu, Game Catalog **filters** open as a left drawer/sheet (desktop collapse rail does not apply), Chat slide-out goes full-width with channels stacked above messages, library tiles clamp denser, and pagination wraps full-width (your saved tile preference still applies on desktop).

## First things to try

1. Open **Game Catalog** and filter by platform or Signals (sticky Filters on desktop; drawer ≤900px). **Tile / Rows / Grid** in the top bar changes the layout (remembered in this browser). **Grid** is genre shelves like Discover. Tile size is the TopNav percent slider (Tile, Rows, Grid, and Discover). **Ctrl+K** searches titles from any page; an empty box shows recent and household-favourite titles.
2. Open **Systems** and pick a console family — or **More → Ways to Play** for Browser / Companion / Catalog across the catalog.
3. Open a game → details (media stage when a trailer or screenshot exists — click a screenshot for the lightbox, About when a storyline is on file, store requirements/languages only if Steam filled them, Extras & DLC with on-server honesty, store marks) → **Download** (streaming zip).
4. Open preferences (account menu) → sectioned Preferences (decade-room cards + icon pack + tile size; no heavy cards).
5. Optional: **Friends** pill / **More → Friends**, **Chat** pill / **More → Chat** (left slide-out), **News** (tabs), **Notifications** (dense unread inbox), **Help** (accordion starts collapsed), or **Report issue** (Context/Logs collapsed).

More: [library-and-systems.md](library-and-systems.md) · [preferences-themes.md](preferences-themes.md) · [downloads.md](downloads.md) · [social-and-voice.md](social-and-voice.md) · [faq.md](faq.md) · [troubleshooting.md](troubleshooting.md)
