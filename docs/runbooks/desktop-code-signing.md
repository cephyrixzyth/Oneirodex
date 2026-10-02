# Desktop distribution — unsigned only (Windows / macOS / Linux)

> **Doc status:** Active

## Product stance — unsigned only

**Code-signing certificates will never be pursued.** Unsigned desktop builds are the supported distribution path for Oneirodex.

Do **not** buy an EV (or any) code-signing cert for this product, and do not add Apple Developer ID / notarization credentials. Operators should not set signing secrets in GitHub. SmartScreen and Gatekeeper noise on first run of an unknown binary is an accepted tradeoff for self-hosted household use.

**Unsigned is about certificates, not about installers.** Bundling is on: users get a real installer on every platform, it is simply not signed.

## Supported builds

`bundle.active` is `true` in both `tauri.conf.json` and `tauri.thin.conf.json`, so `tauri build` emits installers under `src-tauri/target/<target>/release/bundle/`.

| Flavor | Command | Bundle name |
|---|---|---|
| **Full companion** | `npm run tauri:build` | `Oneirodex_<version>_…` |
| **Thin client** | `npm run tauri:build:thin` | `OneirodexThin_<version>_…` |

The two flavors still share the **bare** Cargo output path (`target/release/oneirodex-desktop[.exe]`), but the bundles no longer collide — `productName` differs, so the installers are separately named and both can sit in one output directory.

### Targets

| Host | Produces |
|---|---|
| Windows | `.exe` (NSIS) |
| macOS | `.app` + `.dmg` |
| Linux | `.deb` + `.AppImage` |

**`.msi` and `.rpm` are deliberately excluded.** Both reject a pre-release version string, and the project ships `1.0.0-beta`. Add them back to `bundle.targets` in both configs when the version becomes a plain `X.Y.Z`.

Thin build uses capabilities `thin-main` / `thin-library` / `social` (no install/FS lifecycle ACL). Full uses `default` + `social`.

Icons live under `clients/desktop/src-tauri/icons/` (generate with `npx tauri icon path/to/app-icon.png` if missing). `.icns` is required for macOS and `.ico` for Windows; both are present.

No env vars or secrets are required for an unsigned build. Do **not** wire `bundle.windows.certificateThumbprint` or org certs.

## GitHub Actions

[`.github/workflows/desktop-build.yml`](../../.github/workflows/desktop-build.yml) builds **six** unsigned artifacts — full and thin, on Windows, macOS and Linux — and uploads each under `oneirodex-<flavor>-<platform>`. There is no signing step.

macOS builds `--target universal-apple-darwin`, so one `.dmg` covers Apple silicon and Intel; `macos-latest` alone would leave Intel Macs with nothing.

`if-no-files-found: error` on the upload is deliberate: "bundling silently produced nothing" is the exact failure this workflow exists to catch.

## Local builds

[`scripts/build-installers.sh`](../../scripts/build-installers.sh) does the same thing on your own machine, including Linux bundles from any host via Docker. See [local-installers.md](local-installers.md). A `.dmg` genuinely requires a Mac — that constraint is Apple's, not CI's.

## Historical note

Earlier CI drafts included an optional `signtool` path gated on `WINDOWS_CERTIFICATE` / `WINDOWS_CERTIFICATE_PASSWORD`. That path is **unsupported and removed**. Do not reintroduce cert purchase or signing secrets.

Bundling itself was off (`bundle.active: false`) until the cross-platform pass. While it was off, `scripts/build-installers.sh` and [local-installers.md](local-installers.md) documented `.msi` / `.dmg` / `.deb` / `.rpm` / `.AppImage` output that could not be produced — `find … -exec cp` exits 0 with no matches, so the script reported success over an empty directory. That is why `collect()` now fails loudly when a build yields no bundles.
