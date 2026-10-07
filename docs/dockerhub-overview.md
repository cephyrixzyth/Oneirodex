# Oneirodex — a game library for your household

> **Doc status:** Active

![Oneirodex Discover, captured from the live app](https://raw.githubusercontent.com/cephyrixzyth/Oneirodex/main/docs/assets/readme/hero-banner.png)

Oneirodex is a self-hosted home for the games you already own. Scan mounted game folders, organize a shared catalog, enrich it with metadata and artwork, and give your household a polished place to browse, collect, discuss, download, and play supported titles.

It runs as **one container with PostgreSQL included**. Your games stay on your storage, mounted read-only for scanning. App data, generated artwork, settings, and the database stay on persistent storage you control.

**Current release: `__VERSION__`** · Docker Hub tags: [`latest`](https://hub.docker.com/r/cephyrixzyth/oneirodex/tags?name=latest) · [`1.1`](https://hub.docker.com/r/cephyrixzyth/oneirodex/tags?name=1.1) · [`__VERSION__`](https://hub.docker.com/r/cephyrixzyth/oneirodex/tags?name=__VERSION__) · **Platforms:** `linux/amd64`, `linux/arm64` · [AGPL-3.0](https://github.com/cephyrixzyth/Oneirodex/blob/main/LICENSE)

## Take a look

### Browse your library

![Oneirodex library with game covers and collection controls](https://raw.githubusercontent.com/cephyrixzyth/Oneirodex/main/docs/assets/readme/screenshot-library.png)

Search and filter one catalog, open a title for its details, and organize household favorites and collections.

### Discover what to play

![Oneirodex Discover storefront](https://raw.githubusercontent.com/cephyrixzyth/Oneirodex/main/docs/assets/readme/screenshot-discover.png)

Curated shelves bring the catalog, household activity, upcoming releases, news, and deals together. Rows adapt to posters and artwork where available.

### Play from the couch

![Oneirodex Big Picture interface](https://raw.githubusercontent.com/cephyrixzyth/Oneirodex/main/docs/assets/readme/screenshot-big-picture.png)

Big Picture provides a readable, controller-friendly way to browse from a TV. Browser play appears only for systems supported by the configured play engine.

### Manage libraries and scans

![Oneirodex admin library and scan controls](https://raw.githubusercontent.com/cephyrixzyth/Oneirodex/main/docs/assets/readme/screenshot-admin-libraries.png)

Admins can configure scan roots, review matches, manage artwork, invitations, integrations, and server health.

### Watch a short tour

[![Watch the Oneirodex tour](https://raw.githubusercontent.com/cephyrixzyth/Oneirodex/main/docs/assets/readme/poster-tour.png)](https://raw.githubusercontent.com/cephyrixzyth/Oneirodex/main/docs/media/video/howto/howto-tour.mp4)

[Browse the narrated how-to videos](https://github.com/cephyrixzyth/Oneirodex/tree/main/docs/media/video/howto) · [See all captured screens](https://github.com/cephyrixzyth/Oneirodex/tree/main/docs/media/screenshots)

## What you get

- **A shared game catalog:** scan mounted folders, review metadata matches, and organize games by library and system.
- **Household accounts:** invite people, share collections and favorites, and use chat and presence features.
- **A modern browser UI:** browse, discover, follow news, view release information, and download files from your own server.
- **Optional play paths:** browser emulation for supported systems, plus the Oneirodex desktop companion for local handoff and play.
- **Artwork you control:** use built-in art tools or connect a trusted workstation running a compatible Forge / AUTOMATIC1111 API.
- **Optional integrations:** connect metadata and game-store services from the admin setup. Provider credentials remain yours to configure.
- **One persistent application directory:** bundled PostgreSQL, generated secrets, logs, settings, themes, covers, and uploads live under `/config`.

Oneirodex does not include game files, firmware, BIOS files, encryption keys, or copyrighted content. Use only software you are authorized to store and access.

## Install with Docker Compose

Create persistent folders first. Store the app data and artwork on a reliable SSD or cache pool; mount the game share read-only.

```yaml
services:
  oneirodex:
    image: cephyrixzyth/oneirodex:__VERSION__
    container_name: oneirodex
    restart: unless-stopped
    ports:
      - "5006:5006"
    environment:
      PUID: "99"
      PGID: "100"
      TZ: "UTC"
      ONEIRODEX_LIBRARY_DIR: /config/library
    volumes:
      - ./appdata:/config
      - /path/to/games:/storage:ro
      - ./appdata/library:/app/oneirodex/static/library
    stop_grace_period: 60s
```

Then run:

```sh
docker compose up -d
```

Open `http://SERVER-IP:5006/`. The first visit starts the setup flow. Keep `/config` backed up; it contains the database and generated secrets. Never mount your game share read-write for scanning.

## Install on Unraid

Install **Oneirodex** from Community Applications, set the Appdata path on your cache/SSD, and point **Games** at the host share to scan. The template mounts games read-only and keeps the database and generated artwork under appdata. Optional Forge artwork, ClamAV, and TRAWL integrations are off until configured.

For an installed container, use Unraid's **Docker** page and run the available update action. If Unraid does not offer an update, enable **Advanced View** and choose **Force Update** to pull the current image. Refreshing the Community Applications catalog updates the install template; it does not pull a new container image. After updating, check the app's `/awake` endpoint for `__VERSION__`. Keep a current Appdata backup before upgrading. See the [Unraid install, storage, backup, and update guide](https://github.com/cephyrixzyth/Oneirodex/blob/main/docs/runbooks/unraid-community-apps.md).

## Image tags and updates

- `__VERSION__` pins this exact release. Older exact patch tags remain available.
- `1.1` is a moving alias for compatible patch updates in the 1.1 minor line.
- `latest` advances with each stable release.

GitHub Actions runs the release checks before publishing multi-architecture images. Compare the running app's version on its `/awake` endpoint after updating. Read the [release notes](https://github.com/cephyrixzyth/Oneirodex/releases/tag/v__VERSION__) before upgrading and keep a current `/config` backup.

## Learn more

- [Project source and issue tracker](https://github.com/cephyrixzyth/Oneirodex)
- [All Oneirodex documentation](https://github.com/cephyrixzyth/Oneirodex/tree/main/docs)
- [User getting-started guide](https://github.com/cephyrixzyth/Oneirodex/blob/main/docs/user/getting-started.md)
- [Docker Compose and Unraid operator guide](https://github.com/cephyrixzyth/Oneirodex/blob/main/docs/runbooks/unraid-community-apps.md)
- [Unraid Community Apps template](https://github.com/cephyrixzyth/unraid-templates/blob/main/oneirodex/oneirodex.xml)
- [License](https://github.com/cephyrixzyth/Oneirodex/blob/main/LICENSE)
