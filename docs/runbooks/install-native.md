# Native install — Linux · macOS · Windows

Running Oneirodex directly on the machine, without Docker. Pick this when you
want the server to see the host's own disks and mounts with no bind-mount layer
in between, or when Docker is not available.

For containers, use [docker-compose-deploy.md](docker-compose-deploy.md) or
[unraid-deploy.md](unraid-deploy.md) instead.

## What you need

| | |
|---|---|
| Python | 3.11+ |
| PostgreSQL | 17+ (16 works; 17 is what CI and the images use) |
| Disk | ~1 GB for the app and dependencies, plus covers/artwork under `UPLOAD_FOLDER` |
| Port | 5006 by default |

The installers below check these, create a virtual environment, create the
databases, and write a `.env` with a generated `SECRET_KEY`. None of them
install Docker, and none of them expose Oneirodex to the internet — put a
reverse proxy in front for that ([login-rate-limit-proxy.md](login-rate-limit-proxy.md)).

## Standalone (preview): no PostgreSQL to install

[ADR 0011](../adr/0011-standalone-bundled-postgres.md) adds a third way in:
a standalone install carries its own PostgreSQL 17 and runs it in your user
account. No administrator rights, no system service, nothing listening beyond
`127.0.0.1`. **Status:** the launcher is proven end to end on Linux and on a
real Windows 11 machine (EDB PostgreSQL 17 archive, no admin rights). Packaged
downloads do not exist yet; macOS and Steam Deck are called supported only after
a run on a real machine.

```bash
python -m oneirodex_standalone --pg-home /path/to/bundled-postgres [--data-dir DIR] [--port 5006]
```

| | |
|---|---|
| Data folder | `%LOCALAPPDATA%\Oneirodex` (Windows), `~/Library/Application Support/Oneirodex` (macOS), `~/.local/share/oneirodex` (Linux), or `--data-dir` |
| Inside it | `pgdata/` (the database), `library/` (themes, icon packs, artwork, saves, fonts and caches), `logs/postgres.log`, `standalone.json` (generated database password, secret key and port; readable only by you) |
| Install folder | Never written to, so it can be read-only (Program Files, a signed app bundle) |
| First start | Creates the database cluster with an OS-independent collation, runs the normal startup (migrations, setup), then serves `http://127.0.0.1:5006` |
| While running | If the database stops unexpectedly it is restarted; if it keeps stopping (more than 5 times in 10 minutes), everything shuts down |
| Stopping | Ctrl+C or a normal terminate stops the server, then the database. On Windows the database and server also end if the launcher is killed outright (Task Manager); the database then recovers on the next start |
| Firewall | Everything is on `127.0.0.1`, but per-app firewalls (Portmaster, GlassWire, some antivirus suites) can still drop local connections to the bundled, unsigned `postgres.exe`: the first start then hangs and fails with a connection timeout. Allow that program's incoming and outgoing connections on `127.0.0.1`; the port is chosen at random, so a rule for one port is not enough |

`--pg-home` takes either an archive with `bin/` (Windows/macOS style) or the
relocated Linux layout (`usr/lib/postgresql/17/bin` plus `libs/`) built by
`scripts/spikes/desk03/proof_d/make_bundle.sh`.

The launcher does this by setting `ONEIRODEX_LIBRARY_DIR` to `<data folder>/library`.
URLs do not change: files are still served at `/static/library/`.

Moving to a household server later: `python -m oneirodex_standalone export`
here, then `import` on the server ([standalone-move.md](standalone-move.md)).

---

## Linux

```bash
git clone --depth 1 https://github.com/chrisjrovira/oneirodex.git
cd oneirodex
chmod +x install-linux.sh
./install-linux.sh
```

Detects apt / dnf / yum / pacman / zypper and installs Python, PostgreSQL and
build tools, then configures the database and `.env`.

| Flag | Effect |
|---|---|
| `--games-dir PATH` | Games folder (prompted for otherwise) |
| `--library-roots S` | Extra scan locations — see [remote-scan-locations.md](remote-scan-locations.md) |
| `--port PORT` | Serve on a port other than 5006 |
| `--no-db` | Skip PostgreSQL; point `DATABASE_URL` at an existing server |
| `--dev` | Also install `requirements-dev.txt` |
| `--force` | Overwrite an existing `.env` / `config.py` |
| `--verbose` | Show the full output of every step |

```bash
./install-linux.sh --games-dir /srv/games \
  --library-roots 'NAS ROMs=/mnt/nas/roms|Archive=/mnt/archive'
```

Start it: `./startweb.sh` — then open http://localhost:5006

### Database role (what the installer does and does not touch)

The installer creates one dedicated role, `oneirodexuser`, with a generated
password that goes into `.env` (mode `600`), plus `pg_hba.conf` password rules
for that role on the `oneirodex` database. Oneirodex connects as that role only.
It never sets, resets or relies on a password for the `postgres` superuser, and
the superuser keeps its distro default (peer over the local socket).

> **Installed with an older `install-linux.sh`?** Earlier versions ran
> `ALTER USER postgres WITH ENCRYPTED PASSWORD 'postgres'` and added `md5` rules
> for `postgres` to `pg_hba.conf`, which left a known superuser password on the
> host. Fix it once:
>
> ```bash
> sudo -u postgres psql          # then, at the prompt: \password postgres
> # or drop password login for the superuser altogether:
> #   ALTER USER postgres PASSWORD NULL;
> ```
>
> Then remove the lines ending in `postgres … md5` (`local`, `127.0.0.1/32` and
> `::1/128`) from the block under `# Added by Oneirodex installer` in
> `pg_hba.conf` (`sudo -u postgres psql -tAc "SHOW hba_file;"` prints the path)
> and run `sudo systemctl reload postgresql`. The `oneirodexuser` lines stay.

### Run at boot (systemd)

```ini
# /etc/systemd/system/oneirodex.service
[Unit]
Description=Oneirodex
After=network-online.target postgresql.service
Wants=network-online.target
# Wait for the share, or the first scan after a reboot finds an empty folder
RequiresMountsFor=/mnt/nas/roms

[Service]
Type=simple
User=oneirodex
Group=oneirodex
WorkingDirectory=/opt/oneirodex
ExecStart=/opt/oneirodex/startweb.sh
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now oneirodex
journalctl -u oneirodex -f
```

`RequiresMountsFor` is the line people leave out. Without it systemd starts
Oneirodex before the NAS mount is ready and the first scheduled scan sees
nothing.

---

## macOS

```bash
git clone --depth 1 https://github.com/chrisjrovira/oneirodex.git
cd oneirodex
chmod +x install-macos.sh
./install-macos.sh
```

Homebrew is required and is **not** installed for you — the official installer
is a script fetched over the network and run with your privileges, which is your
call to make, not the script's. If `brew` is missing you get the command and an
exit.

The installer takes the same flags as the Linux one. Homebrew's PostgreSQL
trusts the local account, so `DATABASE_URL` connects as you with no password.

Start it: `./startweb.sh`

### Run at login (launchd)

```xml
<!-- ~/Library/LaunchAgents/com.oneirodex.server.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.oneirodex.server</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/oneirodex/startweb.sh</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/YOU/oneirodex</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/YOU/oneirodex/oneirodex.log</string>
  <key>StandardErrorPath</key><string>/Users/YOU/oneirodex/oneirodex.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.oneirodex.server.plist
```

A `LaunchAgent` runs in your login session, so Finder-mounted shares are
visible. A `LaunchDaemon` (boot-time, no session) is not — it cannot see
`/Volumes` mounts made by Finder at all. If you need boot-time start with
network libraries, mount them with autofs first; see
[remote-scan-locations.md](remote-scan-locations.md#macos-host).

macOS may also withhold folder access from a background process. If a scan sees
an empty folder that is not empty, grant **Full Disk Access** to the terminal or
the launchd job in System Settings → Privacy & Security.

---

## Windows

```powershell
git clone --depth 1 https://github.com/chrisjrovira/oneirodex.git
cd oneirodex
.\install-windows.ps1
```

If PowerShell blocks the script, allow it for this session only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Python and PostgreSQL are checked, not installed — both are system-wide changes
that prompt for elevation, so the script prints the exact `winget` command and
stops:

```powershell
winget install --id Python.Python.3.12 --source winget
winget install --id PostgreSQL.PostgreSQL.17 --source winget
```

The installer finds `psql.exe` under `C:\Program Files\PostgreSQL\*\bin` even
when it is not on `PATH`, so a stock PostgreSQL install needs no extra work.

| Parameter | Effect |
|---|---|
| `-GamesDir PATH` | Games folder |
| `-LibraryRoots S` | Extra scan locations (prefer UNC over mapped drives) |
| `-Port PORT` | Serve on a port other than 5006 |
| `-SkipDb` | Use an existing PostgreSQL database |
| `-Dev` | Also install `requirements-dev.txt` |
| `-Force` | Overwrite an existing `.env` / `config.py` |

```powershell
.\install-windows.ps1 -GamesDir 'D:\Games' -LibraryRoots 'NAS ROMs=\\nas\roms'
```

Start it: `.\startweb_windows.cmd`

### Run as a service

Windows has no built-in way to run a script as a service. Two workable options:

**Task Scheduler** (no extra software) — create a task that runs
`startweb_windows.cmd` *At startup*, under a **real user account** with *Run
whether user is logged on or not*. A real account matters: `LocalSystem` cannot
authenticate to a network share, so a NAS library goes unreachable.

**NSSM** for a proper service entry:

```powershell
nssm install Oneirodex "C:\oneirodex\startweb_windows.cmd"
nssm set Oneirodex AppDirectory "C:\oneirodex"
nssm set Oneirodex ObjectName ".\oneirodex-svc" "PASSWORD"
nssm start Oneirodex
```

Either way, mapped drive letters are per-user and will not resolve — use UNC
paths in `ONEIRODEX_LIBRARY_ROOTS`. Members using the desktop companion with a
UNC root list that share under **Trusted network shares** in the companion
([desktop-companion.md](../user/desktop-companion.md#trusted-network-shares-unc-library-roots)).

---

## After installing

1. Open http://localhost:5006 — the setup wizard creates the first admin.
2. **Admin → Libraries & scans** — add a library, point it at a folder, scan.
   Extra scan locations appear in the **Scan location** picker
   ([remote-scan-locations.md](remote-scan-locations.md)).
3. **Admin → Settings** — API keys, modules, SMTP
   ([settings-modules.md](../admin/settings-modules.md)).

## Upgrading

```bash
git pull
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
./startweb.sh
```

Schema migrations run on boot. `.env` is never overwritten by `git pull`; new
keys are added to `.env.example`, so diff the two after a major upgrade.

Coming from **≤ 0.1.0**: `DATA_FOLDER_WAREZ` was removed. Rename it to
`DATA_FOLDER_GAMES` or the app starts with no games folder.

## Resetting

```bash
./startweb.sh --force-setup         # Windows: .\startweb_windows.cmd --force-setup
```

Drops and recreates every table and re-runs the setup wizard. It destroys the
library database — game *files* on disk are untouched.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `SECRET_KEY environment variable is not set` | `.env` was not loaded, or still has the placeholder. Start via `startweb.sh`, not `python asgi.py` |
| `connection refused` on 5432 | PostgreSQL is not running — `systemctl status postgresql`, `brew services list`, or Services on Windows |
| `database ... does not exist` | Re-run the installer, or `createdb oneirodex` |
| Port 5006 in use | `PORT=5010 ./startweb.sh`, or `--port` at install time |
| Library grid unstyled | Frontend bundles missing — `cd frontend/member-app && npm ci && npm run build` |
| Scan sees an empty folder | Permissions or an unmounted share — [remote-scan-locations.md](remote-scan-locations.md#troubleshooting) |

More: [../admin/troubleshooting.md](../admin/troubleshooting.md) ·
[container-wont-start.md](container-wont-start.md) (Docker)
