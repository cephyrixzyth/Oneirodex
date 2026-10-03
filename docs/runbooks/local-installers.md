# Building installers without GitHub

> **Doc status:** Active

Produce Windows, macOS and Linux desktop installers on your own machine. The
CI workflow (`.github/workflows/desktop-build.yml`) is a convenience, not a
requirement.

```bash
./scripts/build-installers.sh                  # bundle for this host
./scripts/build-installers.sh --linux          # Linux bundles via Docker
./scripts/build-installers.sh --thin           # thin client
./scripts/build-installers.sh --linux --thin   # thin client, Linux bundles
```

Output lands in `dist-installers/` (gitignored). The script **fails loudly** if a
build produced no bundles rather than reporting success over an empty directory.

## What each host can build

| Host | Produces | Notes |
|---|---|---|
| Windows | `.exe` (NSIS) | Native. Needs Rust + Node 22. |
| Linux | `.deb`, `.AppImage` | Native, or from any host with `--linux`. |
| macOS | `.dmg`, `.app` | **Mac required** — see below. |

`.msi` and `.rpm` are not built: both reject a pre-release version string. The
project is on a plain `1.0.0` now, so they can be turned on; they stay off until a
build has proven them. They can be added back to
`bundle.targets` in `clients/desktop/src-tauri/tauri.conf.json` (and
`tauri.thin.conf.json`) once the version is a plain `X.Y.Z`.

Both flavors bundle under distinct product names (`Oneirodex` vs
`OneirodexThin`), so full and thin installers can share one output directory.

## Why macOS needs a Mac

This is the one real constraint and it is not something CI hides from you.
Tauri's macOS bundler shells out to `hdiutil` for the disk image, `codesign`
for signing and the `.icns` toolchain for icons. All three are Apple-only and
none of them cross-compile. GitHub Actions builds `.dmg` by renting a macOS
runner, not by cross-compiling — so dropping CI does not lose a capability you
otherwise had.

If you have no Mac, the options are a macOS runner, a rented build host, or
shipping Windows and Linux only.

CI builds macOS with `--target universal-apple-darwin` so one disk image serves
Apple silicon and Intel. Locally, a plain `./scripts/build-installers.sh` on a
Mac produces a `.dmg` for that Mac's own architecture; add
`-- --target universal-apple-darwin` to `npm run tauri:build` for a universal one
(requires `rustup target add x86_64-apple-darwin aarch64-apple-darwin`).

## Prerequisites

- **Rust** — <https://rustup.rs>
- **Node 22** (pinned in `.nvmrc`; every `package.json` sets `engines: ">=22 <23"`)
- **Windows**: MSVC build tools + WebView2 (present on Windows 11)
- **Linux/Docker**: the script installs `libwebkit2gtk-4.1-dev`, `libgtk-3-dev`
  and friends inside the container, and pulls Node from NodeSource (Debian
  bookworm still ships Node 18). Those webkit headers are exactly why a Linux
  bundle cannot be produced natively on Windows.

## Signing

Bundles are **unsigned** by default, which matches the project's stance that the
companion is unsigned unless an operator supplies certificates — see
[desktop-code-signing.md](desktop-code-signing.md), where that stance is locked.

- Windows: SmartScreen warns on first run.
- macOS: Gatekeeper blocks until signed *and* notarised with an Apple
  Developer ID — signing alone is not enough on current macOS.

## Unraid

The server image is separate from the desktop companion. For the Unraid
template's icon field, point at the running server:

```
http://<unraid-ip>:5006/static/icons/oneirodex-256.png
```

`oneirodex-512.png` sits alongside it. Both ship inside the image under
`/app/oneirodex/static/icons/`.
