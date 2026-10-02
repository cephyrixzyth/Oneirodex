# Downloads

> **Doc status:** Active

## Where

- Top nav **Downloads** → `/downloads` (React page: queue + history).
- **Download** on a game details page streams a zip of the on-disk title (and selected version when multi-version exists). Versions marked **Missing on disk** hide Download — the UI does not offer a zip for absent paths.

## Behavior

- Download is server-side streaming; large titles depend on disk and network to the Oneirodex host.
- Version list honesty: `path_missing` / `downloadable` / measured `size` · **Default** chip on the base install · librarians/admins can **Remove missing versions** (orphan cleanup).
- Web UI does not install/extract on your PC — that needs the optional desktop companion (**Install / Update / Uninstall**). See [desktop-companion.md](desktop-companion.md).
- History lists past downloads for your account; queue shows in-progress work when the client/server reports it.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Button missing / disabled | No path on disk (`path_missing` / not downloadable), ACL, or unfinished scan |
| “Missing on disk” on a version | Path gone after move/delete — librarian **Remove missing versions** cleans orphans |
| Download fails mid-stream | Disk full, path moved, reverse-proxy timeouts |
| Page unstyled | Missing `member-app.css` — admin rebuild |

Related: [getting-started.md](getting-started.md) · admin scan docs [libraries-and-scans.md](../admin/libraries-and-scans.md)

## Acquire (optional)

- Top nav / More → **Acquire** (`/acquire`) when Arr and/or debrid modules are enabled.
- Searches admin-configured native Torznab/Newznab indexers and optional Prowlarr/Jackett hubs. Hits show the **indexer** name; warnings from search (if returned) appear above results.
- If no native/hub indexers are ready, the page shows an empty state pointing admins to **Admin → Arr**.
- Sending to qBit / Transmission / SABnzbd / NZBGet / debrid is **librarian or admin** only.
