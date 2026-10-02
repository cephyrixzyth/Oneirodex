# Free games (News)

> **Doc status:** Active

Oneirodex polls major stores and a public giveaway aggregator so household members can **see what’s free right now**, get an in-app notification when something new appears, and **claim via store deeplinks**.

This is **not** a DRM download client. Claiming always happens on Steam / Epic / GOG / Amazon / itch / Humble (browser or launcher).

## Where to look

| Surface | What you get |
|---|---|
| **News → Free now** (or News tab **Free now** / `#free-games`) | Active offers with Claim, Open in app, Sync ownership — strip tiles under the News featured composition; empty tab is honest HTTP 200 |
| **Notifications** | Dense unread inbox · `Free on …` alerts for newly seen offers (opt out under Alert preferences) |
| Deep link | `/news#free-games` |

## Claim (both avenues)

| Avenue | When | Action |
|---|---|---|
| **A — Deeplink** | Always | **Claim** (HTTPS) or **Open in app** (`steam://` / Epic launcher URI when that store is linked) |
| **B — Connected assist** | Store linked under Ownership | **Sync ownership** registers the title. Steam / GOG / Epic re-run live library sync when a token is saved |

Oneirodex never silently redeems DRM. Claim on the store first (A), then Sync ownership (B) so badges update.

## Stores

| Store | Typical source | Claim |
|---|---|---|
| Epic | Official freeGamesPromotions | Store page / Epic launcher URI if Epic linked |
| Steam | Featured 100% off | Store page / `steam://openurl/…` if Steam linked |
| GOG · Amazon (Prime) · itch · Humble | GamerPower giveaways API | HTTPS claim URL |

Xbox / PlayStation freebies may appear when the aggregator lists them; no special launcher deeplink yet.

GamerPower also reposts offers the official Epic and Steam feeds already carry, decorated — Epic's "Alone With You" arrives as "Alone With You (Epic Games) Giveaway". Those reposts are dropped so a title is listed once per store; a genuine second offer on a *different* store still shows. Tile art comes from the store's portrait key where one exists (Epic tall keys, Steam's 600×900 capsule, including for Steam giveaways routed through GamerPower). GOG, itch, Humble and IndieGala offers — and Epic ones routed through GamerPower — have no such URL, so their cover is looked up on IGDB by title and cached for a month, which is about one call per new title rather than one per sync. A title IGDB does not know keeps the aggregator's wide banner, as does every offer when `ENABLE_FREE_GAMES_COVER_LOOKUP` is off or IGDB credentials are unset.

## Operator flags

| Env | Default | Meaning |
|---|---|---|
| `ENABLE_FREE_GAMES` | `true` | Poller + API |
| `FREE_GAMES_POLL_HOURS` | `3` | Refresh interval (1–24) |
| `ENABLE_FREE_GAMES_COVER_LOOKUP` | `true` | Look a cover up on IGDB when the store has no portrait of its own. Needs IGDB credentials; without them tiles keep the aggregator banner |

Outbound HTTP must reach Epic / Steam / GamerPower from the container host.

## Member prefs

`notify_free_games` (default on) — Notifications → Preferences → **Free games**.

## Non-goals

- Silent DRM redeem / OAuth claim without opening the store
- DRM install queues inside Oneirodex
- Email digests of free games alone (included in the optional daily notification digest instead)
