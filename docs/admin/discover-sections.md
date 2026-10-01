# Discover sections (storefront shelves, zones & events)

> 🎬 Watch (narrated): [shelves & events](../media/video/howto/howto-admin-discover.mp4) — [all how-to videos, with transcripts](../media/video/howto/README.md)

Admin → **Discovery Sections Management** (`/admin/discovery_sections`) controls the shelves members see on `/discover`.

## Built-in vs custom

- **Built-in shelves** (Continue Playing, New Arrivals, Most Favorited, libraries, …) can be **reordered** and **hidden** (visibility toggle) but not deleted.
- **Custom shelves** (`section_type = 'custom'`) are admin-authored, shown with a **Custom** badge. Add one with **+ Add shelf**; edit/delete with the row's pencil/trash icons.
  - They were called *custom zones* until 2026-09-06. A **zone** now means only one thing — a page of shelves under Discover (`/discover/zone/<slug>`) — and a custom shelf is one of the things a zone can contain. The stored `section_type` is unchanged (UID-059).

## Latest Games vs New Library Games

Two shelves that sound alike and answer different questions. They used to be one
shelf answering the second question under the first one's name.

| Identifier | Order | Answers |
|---|---|---|
| `latest_games` | `first_release_date` descending, **future dates excluded** | "What has come out recently, in the world?" |
| `new_library_games` | `date_created` descending | "What has recently appeared *here*?" |

`latest_games` skips unreleased titles on purpose — that is the `upcoming`
shelf's subject, and leaving them in made both shelves open with the same game.
A title with no known release date never appears in `latest_games`; it will
still show under `new_library_games`.

`new_library_games` is seeded for new installs and added to existing ones the
next time init runs (both seeders are additive and skip identifiers that already
exist). If you do not see it, it has not been seeded yet — add it by hand with
identifier `new_library_games`, or re-run init.

## Storefront shelves

Built-in shelves that hide when empty. `curated_for_you` / `upcoming` /
`extras_missing` are on-box only. **Deep discounts** is the exception: it
reads CheapShark (public HTTPS) and never checks out.

| Identifier | What it shows |
|---|---|
| `curated_for_you` | Unplayed titles in genres the member already favourites, best-rated first, then most recently added |
| `upcoming` | **What is coming that the household does not hold**, soonest first, as article tiles with the release date as the badge date. Two sources: library titles still ahead of release that *this member* favourited or requested (cover, links to the title), and the IGDB release cache the licensed-title report keeps (`igdb_platform_releases`) for platforms the member's libraries hold — titles whose IGDB id matches **no** library row (no cover; links to that platform's licensed catalogue). A held title the member has not asked for is **not** upcoming to them (changed 2026-09-17). Horizon 365 days; no new scraping |
| `store_deals` | **Deep discounts** — CheapShark deals ≥75% off across Steam / GOG / Humble / Epic. Article tiles with HTTPS store redirects. Skips titles on the member’s ownership register. No cart, no DRM download queues, no prices on Game tiles. CheapShark requires an identifying User-Agent (`Oneirodex/1.0 (self-hosted library)`); their Savings sort uses `desc=0` for steepest-first. The shelf hides when a successful pull is empty; a failed pull keeps the last snapshot. Seeded on next init (`display_order` `-8`). |

Honesty rules worth knowing before you go looking for a bug:

- `curated_for_you` **excludes anything already favourited**. A "for you" shelf
  that only shows what you already picked is noise.
- A member with no favourites yet has no signal, so the shelf returns nothing
  and is **hidden** rather than padded with a random sample dressed up as a
  recommendation. This is why a fresh account sees fewer shelves.
- `upcoming` is empty when nothing the member wishlisted is ahead of release **and** the IGDB release cache has nothing coming for the platforms they hold — refresh the cache from **Admin → ROM reference sets** (one platform per click). Also expected.
- Both are ACL-filtered per member like any other shelf.

## Layouts

Each section carries a `layout` controlling its storefront treatment:

| Layout | Use |
|---|---|
| `shelf` | Default — standard horizontal row |
| `hero` | Large feature treatment, for the thing you want seen first |
| `carousel` | Rotating showcase |

## Events (shelves with a schedule)

A shelf given a time window becomes an **event**: it renders only inside that
window and disappears on its own afterwards. Use it for seasonal collections,
a weekend spotlight, or a themed run.

- `starts_at` / `ends_at` are both optional. Set only `starts_at` for "from now
  on", only `ends_at` for "until", or both for a fixed run.
- Timestamps are **UTC**; naive values are read as UTC.
- A shelf must *also* be visible — `is_visible = false` hides it regardless of
  schedule, so the visibility toggle stays a reliable override.
- Outside its window a shelf is simply absent from `/api/discover/sections`;
  members see no placeholder or "coming soon" state.

Schedule via `PUT /admin/api/discovery_sections/<id>/schedule`.

## Zone modes

| Mode | Config | Notes |
|---|---|---|
| **Manual game list** | Textarea of game UUIDs (one per line or comma-separated) | Up to **60** games, shown in the order listed; find a game's UUID on its admin details page |
| **Filter** | `library` \| `platform` \| `genre` + a value | Live query — the shelf grows automatically as matching games are added |

Both modes are ACL-filtered per member on `/discover` (parental / library-access rules apply same as any other shelf). Shelf depth is covered under [Row depth](#row-depth-and-the-see-all-tile) below.

## How a shelf is built

The member feed is assembled in two passes, in `oneirodex/routes_discover.py`:

1. **Selection** — each visible, in-window shelf resolves to `Game` rows and
   nothing more. One query per shelf.
2. **Hydration** — every shelf's games are then fetched *together* by
   `oneirodex/utils/discover_hydrate.py`: one query for all cover images, one
   for update counts, one per card relationship, and a single companion-presence
   check for the whole page. Folder-level checks for local metadata and images
   are memoised per path, so a folder backing several shelves is stat'd once.

The practical effect is that feed cost tracks the number of *shelves*, not the
number of *tiles* — which is what makes deeper shelves affordable. A title that
appears on several shelves is fetched once.

`tests/test_discover_hydrate.py` guards the batching by counting queries; it
fails if anything in the card serializer starts querying per game again.

## Personal rows

Four shelves are about the member rather than the catalogue. They seed ahead of
the chart shelves — what you were doing, then what changed in your library, then
what everyone else likes — and an admin can reorder or hide them like any other.

| Identifier | Shows | Notes |
|---|---|---|
| `continue_playing` | Titles the member played most recently | Exempt from cross-row dedupe: what you are actually playing belongs here whether or not it also appears elsewhere |
| `friends_playing` | Titles accepted friends played recently | Privacy-gated, see below. Two friends on one title is one tile, dated by whoever played it last |
| `game_updates` | Titles whose **update files** landed recently | Distinct from `last_updated`, which reads the `Game.last_updated` metadata timestamp |
| `extras_missing` | Engaged titles whose catalogued extras are **not on the vault** | Played or favourited only — never stats the whole library. Hidden when empty. No sale chrome. Seeded on next init (`display_order` `-15`) |
| `news` | Announcements and live free-game offers | Carries articles, not games — see [Row kinds](#row-kinds) |

Every one of these states **why it is there** under the row title. That line is
required for any ranked row: an unexplained recommendation reads as an ad, and a
named one reads as a feature.

### Friends' activity is opt-out, and friends-only

`friends_playing` puts one member's activity on another's home page, so it is
gated on `UserPreference.share_activity`:

- **Default on**, because the common install is a household — but scoped to
  **accepted friends only**, never server-wide.
- Any member can switch themselves off under **Notifications → Preferences**.
- A member with no preferences row at all counts as sharing. Absence is not an
  opt-out; only an explicit "off" is.
- A *pending* friend request is not a friendship, and a stranger on the same
  server is not a friend.

## Row kinds

Most rows are made of games. The news row is made of articles, and the payload's
`item_kind` says which:

| `item_kind` | Payload key | Card |
|---|---|---|
| `games` | `games` | The shared game tile |
| `articles` | `items` | A news tile — announcement or free-game offer |

A row sends one key or the other, never both: mirroring the list would serialize
every tile twice for no reader's benefit. On the client, `rowItems(section)` in
`components/DiscoverShelf.jsx` is the one place that branch lives.

Expired giveaways are dropped from the news row rather than shown — a "free now"
row advertising a finished giveaway is worse than a shorter row.

## Row depth and the "see all" tile

A shelf ships a **window** of `ROW_WINDOW` (12) tiles and fills itself in as the
member scrolls it, up to a ceiling of `ROW_MAX` (40). Both live in
`oneirodex/utils/discover_providers.py`.

Forty is a ceiling, not a quota. A shelf shows what it honestly has — no
padding from looser criteria to reach a number — so a small library gets short
shelves, which is the truth. The **See all** tile appears at the end of a shelf
when the shelf holds more than it will ever display, **or** when the row has a
real destination of its own (the News row always links to `/news`). A "see all"
that leads to the same tiles would be a lie.

Where that tile goes depends on the shelf:

| Shelf | Destination |
|---|---|
| Filter zone on `genre` | `/discover/hub/genre/…` — unplayed / newly added / loved shelves for that genre; **Browse the catalog** is still the full list |
| Filter zone on `platform` | `/library?library_platform=…` — the catalog already parses this |
| News / articles | `/news` — the full News page, not a second Discover shelf of the same articles |
| Everything else | `/discover/<identifier>` — a paginated page for that shelf alone |

A **genre hub** is not an admin `DiscoverySection`. `GET /api/discover/hubs/genre/<name>` builds the rows on the fly (404 if the genre name is unknown). Empty hub shelves are omitted. Hub rows cannot be pinned or hidden.

A library-filtered zone deliberately does **not** deep-link: the Library page has
no library-scoped URL filter, so the link would silently show everything.

## The on-box recommender

Everything the recommender uses is already on the box: what members favourited,
played, own, downloaded and marked finished, scored against metadata already
scraped. **Nothing leaves the box**, there is no model file, and no heavy
dependency is added to the default install.

Lives in `oneirodex/utils/discover_ml/`. Everything expensive runs on a schedule
and is materialised, so a Discover load is only ever a handful of SELECTs.

### Content is the primary engine, not collaborative filtering

Worth stating plainly, because it is the opposite of how a store-scale
recommender is built. "People who played this also played that" needs a
population. On an install with a handful of members, two titles co-occurring
once is indistinguishable from coincidence — and the recommender would state it
with the same confidence as a real result.

So the engine that actually runs is **content-based**: a member's taste profile
scored against each title's facets. Collaborative filtering *is* implemented and
stays dark until an install has **25 members with at least 3 played titles
each**. Below that floor the job skips it, clears any rows a previously larger
install left behind, and the blend silently falls back to pure content.

### The taste profile

A weighted picture of what a member reaches for, across genre, theme, player
perspective and developer:

| Signal | Weight | Why |
|---|---|---|
| Favourited | 3.0 | A deliberate act, so it counts most |
| Marked beaten or completed | 2.5 | Finishing something says a lot |
| Owned on a store | 1.0 | Weak: a bundle buys fifty games nobody asked for |
| Downloaded | 0.8 | Intent, but lighter than finishing |
| Playtime | `0.5 × ln(1+hours)` | Logarithmic, so one 400-hour obsession does not drown out the twenty titles that better describe a taste |

Everything is decayed by age (halving roughly every 60 days), so a profile
follows a member rather than fossilising around what they liked two years ago.
Rebuilds **replace** rather than merge: a facet that drops out of a taste has to
disappear.

Scoring uses cosine similarity, so a title carrying twenty facets does not
outscore a precise match by overlapping more. A rating prior nudges results but
deliberately cannot overrule affinity — a well-regarded title a member has no
affinity for should not beat a middling one squarely in their taste.

### Because You Played

`because_you_played` is a **template, not a shelf**. It renders nothing itself;
it carries the visibility switch for the rows the recommender generates, one per
title the member has really played. Hide it and the whole family goes away —
including by direct URL.

Anchors are chosen by **playtime**, not recency: a row anchored on something the
member bounced off reads as a misunderstanding rather than a recommendation. At
most three rows are generated, so they compete for the tail of the page rather
than flooding it (the family diversity cap covers them).

`curated_for_you` now reads the profile too, superseding the genre-affinity
draft it shipped with. A member with no profile yet falls back to the original
query — a ranking built on nothing is worse than the simple answer.

### Freshness is rotation, not modelling

The reason the same tiles greet somebody every morning is that nothing remembers
having shown them. Two mechanics fix that, and neither is a recommender:

- **Impression damping.** Titles put in front of a member are recorded on every
  feed build. A title shown repeatedly and never opened is scored down — to a
  floor, never suppressed, because a member who ignored everything should still
  get a feed. **Opening a title clears its damping**: a tile that got clicked has
  earned its place.
- **Daily rotation.** The rotation seed is derived from the member and the date,
  so the feed is stable within a day and different tomorrow. Reshuffling on every
  request would read as broken — tiles moving under the pointer between glances.

Impression recording is best-effort: a feed that failed to render because a
bookkeeping write went wrong costs far more than a lost impression.

### Operating it

| Setting | Default | Effect |
|---|---|---|
| `ENABLE_DISCOVER_ML` | on | Turns the rebuild daemon off entirely |
| `DISCOVER_ML_REBUILD_HOURS` | 24 | Gap between rebuilds (clamped 1–168) |

Taste moves slowly, so nightly is ample; a tighter loop spends the box's disk for
no visible difference. The first rebuild waits a minute after boot, because it
walks every game.

## How many rows, and who gets each title

A feed holds at most **20 rows**. The cap exists so that generated rows compete
for a finite page rather than extending it. Assembly lives in
`oneirodex/utils/discover_feed.py`.

**Order is yours.** Inclusion is decided in code; sequence is not. Rows arrive in
the `display_order` you set on this screen and stay in it — nothing re-sorts by
an internal score, because that would make the drag handle a lie. What assembly
decides is which rows fit and what each one shows.

Slots fill in this order:

| Block | Slots | Rule |
|---|---|---|
| Admin-forced | 0–3 | Capped at three, so a member's pins can never be pushed below the fold |
| Member pins | 0–3 | In the member's own order |
| Everything else | remainder | Your configured order, until the page is full |

**Cross-row dedupe.** Walking the rows in final order, each one drops titles an
earlier row already showed and backfills from its own depth — which is why rows
over-fetch. Rules worth knowing:

- A row claims what it **renders**, not everything it could reach by scrolling.
  Claiming full depth would let two rows empty a modest library. The trade is
  that scrolling one row very deeply can still reach a title another row showed.
- `continue_playing` is **exempt**: it neither filters nor claims. What you are
  playing belongs on that row regardless, and claiming it would strip the charts
  of exactly the titles most likely to be in them.
- A row thinned *by dedupe* below `min_fill` (4) is dropped. A row that was
  **always** that short is kept — a curated three-game zone is not a starved row,
  and hiding it would be the feed overruling whoever built it.
- Dropping a starved row frees its slot for a row that missed the cut. This is
  why the cap and the dedupe run together rather than one after the other.

**Family diversity.** At most four rows from any one *generated* family. It does
not apply to rows a person configured — every shelf today comes from a section
you arranged and can hide, and silently dropping your sixth zone would be the
feed overruling you. The cap is there for what the recommender will generate.

### Forcing a shelf to the top

`PUT /admin/api/discovery_sections/<id>/pin` with `pin_rank` (a number, lowest
first) forces a shelf into the reserved block on every member's feed. Send
`null` to release it back to its `display_order` position.

Only the **first three** forced shelves take effect. That cap is deliberate: a
member gets three pins of their own, and an admin who could force ten would push
every member's pins below the fold on their own home page.

Forcing composes with scheduling — a forced shelf outside its event window is
still hidden, because visibility and schedule are checked first.

### Surprise me (INSP-4b)

`GET /api/discover/surprise` returns one card drawn at random from the top
`DRAW_WIDTH` (12) of the member's ranking over their unengaged titles, plus up to
six of their strongest profile genres as `genres`. Optional `genre=<id>` narrows the
draw (400 for a non-integer, 404 for an unknown id); `exclude=<uuid,...>` skips
recent picks, and an exhausted band starts over rather than returning empty.
An empty draw is `game: null` with a reason, not an error. It is not a
`DiscoverySection` — nothing to arrange, hide or pin — and it writes nothing:
not an impression, not a taste signal. Code: `utils/discover_ml/surprise.py`.

### Members pin their own rows

`GET`/`PUT /api/discover/pins` stores up to three row identifiers per member, in
their order, on `UserPreference.discover_pins`. The member's own control is the
**Pin** button in each row header.

- Pins are **identifiers, not positions**, so reordering shelves does not move
  somebody's pins off the row they chose.
- A pin sent for a row that is not on the member's feed is **rejected** — on the
  way in, a bad identifier is a client bug worth surfacing.
- A pin for a row that later **stops existing** is dropped silently on read. A
  genre row can go away when a member's taste moves, and an admin can hide a
  shelf somebody had pinned; neither is an error.
- A fourth pin is rejected rather than silently trimmed, so a pin that vanished
  without a word cannot look like a bug.

### The feed token

`GET /api/discover/sections` returns a `feed_token` alongside the rows. It names
a cached record of which titles each row claimed, and row pagination passes it
back so a row's later tiles skip what the rows above are showing.

Without it the dedupe is cosmetic: it would be undone by the member's first
scroll. On an install with no usable cache the token comes back empty, the feed
still works, and dedupe simply stops at the first window — a degradation, not a
failure. The record lives for 30 minutes.

## Row API

- `GET /api/discover/sections` — the feed. Each shelf carries `games` (the
  window), `total_count` (tiles the shelf holds, ≤ 40), `has_more` (there is more
  beyond the ceiling) and `more_href`.
- `GET /api/discover/rows/<identifier>?offset=&limit=` — one shelf, windowed.
  Backs both the shelf filling itself in and the row page. `limit` is clamped to
  60 and `offset` to 2000, so a caller cannot make the server walk the library.

A row resolves through its `DiscoverySection`, so **a hidden or out-of-window
shelf is unreachable by direct URL too** — the row endpoint is not a way around
the visibility toggle.

## API

- `POST /admin/api/discovery_sections` — create a custom shelf (`section_type=custom`, `mode`, `game_uuids` or `filter_type`/`filter_value`).
- `PUT /admin/api/discovery_sections/<id>` — rename or reconfigure (mode/filter/list) an existing custom shelf.
- `PUT /admin/api/discovery_sections/<id>/schedule` — set `starts_at` / `ends_at` (UTC) and/or `layout`.
- `DELETE /admin/api/discovery_sections/<id>` — remove a custom shelf (built-in sections reject delete).
- Reorder / visibility toggle use the existing discovery-sections endpoints (drag handle, switch).
- `GET /api/discover/sections` — what members actually receive; already ACL-filtered and schedule-filtered.

Validation (`oneirodex/utils/discovery_zones.py`): unknown platform/library/genre values are rejected with a 400; an empty/all-unmatched manual list is rejected rather than silently rendering an empty shelf.

Related: [libraries-and-scans.md](libraries-and-scans.md) · [library-and-systems.md](../user/library-and-systems.md)
