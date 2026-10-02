# SteamGridDB artwork provider

> **Doc status:** Active

Enable community artwork from [SteamGridDB](https://www.steamgriddb.com/) for admin artwork search. Oneirodex uses SteamGridDB for **artwork only** — it never downloads games or DRM payloads.

Supported **search** image types (SteamGridDB API): **cover** (grids), **logo**, **hero**.

Persisted **kinds** (BE-DET-10, `Image.image_type`): `cover` · `screenshot` · `box` · `cart` · `disc` · `logo` · `hero` · `fanart`. Apply may store any of these when you supply a URL; SGDB search still only returns cover/logo/hero.

## Enable

1. Sign in at SteamGridDB and create an API key under **Profile → Preferences**.
2. Set the key in your environment:

   ```bash
   STEAMGRIDDB_API_KEY=your_key_here
   ```

3. Restart Oneirodex (or recreate the Docker container so env vars reload).

Optional: the key can also be stored in `global_settings.steamgriddb_api_key` (env takes precedence), matching the `steam_web_api_key` pattern.

## Verify

- **Admin → Integrations → Artwork** shows Enabled with a masked key preview.
- **API** (admin session required):

  ```http
  GET /api/providers
  GET /api/providers/steamgriddb/search?q=Celeste
  GET /api/providers/steamgriddb/search?q=Celeste&image_type=logo
  GET /api/providers/steamgriddb/search?q=Celeste&image_type=hero
  ```

Without a key, `/api/providers` lists SteamGridDB as disabled and search returns **503** with a clear configuration message.

## Apply artwork

`POST /api/games/<uuid>/artwork/steamgriddb` (admin session) with body:

```json
{ "url": "https://…", "image_type": "cover" }
```

`image_type` / `kind` may be any locked kind (`cover` · `screenshot` · `box` · `cart` · `disc` · `logo` · `hero` · `fanart`). Downloads the image (artwork only), saves under `library/images/`, replaces existing singular rows of that type, and returns `{ image_id, filename, cover_url|url, image_type, kind }`.

IGDB remains available as a second provider for **covers only**. Queue filter: `GET /admin/api/image_queue_list?kind=box`. Per-game: `GET /api/game_images/<uuid>?kind=logo`.

## Admin UI

**Edit Images** for a game includes an artwork search panel: pick SteamGridDB, IGDB, or Giant Bomb, choose cover/logo/hero (SGDB), search, and click a result to apply. Apply failures show the server error text.

**Art studio → Pick & queue** (`/admin/art_studio#images`) is the React admin path for the same search/apply flow plus mass image queue actions.

## Troubleshooting

| Symptom | Check |
|---|---|
| Search returns 503 | `STEAMGRIDDB_API_KEY` unset or container not restarted |
| Search returns 401 | Key revoked or invalid — regenerate at SteamGridDB |
| Empty results | Query spelling; game may not exist on SteamGridDB |
| IGDB + logo/hero | IGDB only supports covers — switch provider or image type |

See also: `.env.example`.
