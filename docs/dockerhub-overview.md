# Oneirodex Docker image

> **Doc status:** Active

The Oneirodex `__VERSION__` release is a self-hosted game library for a household. It scans game folders, organizes matched titles, manages household accounts and collections, and brings browse, news, play and social features together in one private server.

This image includes the web application and its PostgreSQL database. It is available as a multi-architecture Docker image for `linux/amd64` and `linux/arm64`.

## Quick start

The recommended install is Docker Compose. Set a strong `SECRET_KEY`, map persistent application data to `/config`, and map game files read-only to `/storage`. The app listens on port `5006`.

```yaml
services:
  oneirodex:
    image: cephyrixzyth/oneirodex:__VERSION__
    ports:
      - "5006:5006"
    environment:
      SECRET_KEY: replace-with-a-long-random-value
      PORT: "5006"
      ONEIRODEX_LIBRARY_DIR: /config/library
    volumes:
      - ./appdata:/config
      - /path/to/games:/storage:ro
```

For upgrades, set the `APP_IMAGE` tag in the existing Compose environment and recreate the app container. Preserve `/config`; it contains the bundled database and persistent library data. Follow the [Docker Compose quick start](../README.md#-quick-start) and [Unraid guide](runbooks/unraid-community-apps.md) for full configuration and backup steps.

## Image tags

- `__VERSION__` is the immutable release image for the current version.
- `latest` advances with each stable release.
- `1.1` follows compatible patch releases in the current minor line.

Release tags are built only after the repository test workflow passes. The GitHub release also includes full and thin desktop installers for Windows, macOS and Linux.

## Features

- Scan configured, mounted game folders and review metadata matches.
- Keep artwork, themes, uploads and the bundled database on persistent app data.
- Invite household members and share libraries, collections, updates and chat.
- Use the member web app or optional desktop companion.
- Connect optional metadata providers, game stores and a trusted LAN artwork generator.
- Add optional ClamAV or TRAWL sidecars on a private Docker network.

The app does not include game files, console firmware, BIOS files or encryption keys. Only scan and manage software you are authorized to use.

## Links

- [Project and source](https://github.com/cephyrixzyth/Oneirodex)
- [Release notes](https://github.com/cephyrixzyth/Oneirodex/blob/main/CHANGELOG.md)
- [Install and operator documentation](https://github.com/cephyrixzyth/Oneirodex/tree/main/docs)
- [Unraid Community Apps template](https://github.com/cephyrixzyth/unraid-templates/blob/main/oneirodex/oneirodex.xml)
- [Support and bug reports](https://github.com/cephyrixzyth/Oneirodex/issues)
