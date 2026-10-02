# Scan locations beyond the server — Oneirodex

> **Doc status:** Active

Oneirodex scans **any path the service process can open**. That is not the same
thing as "a path on the machine Oneirodex runs on": an SMB or NFS share, a
second internal disk, an external drive, an Unraid user share — all of them are
scannable the moment the host (or the container) has mounted them.

Two jobs, in this order:

1. **Mount it.** Oneirodex does not speak SMB or NFS. The host does. This is an
   OS-level step and it is the same step you would take for any other app.
2. **Declare it.** Tell Oneirodex which mounts are libraries, with
   `ONEIRODEX_LIBRARY_ROOTS` (or `ONEIRODEX_LIBRARY_ROOTS` — the new key wins if both
   are set). Until you do, the admin folder browser and the path
   allowlist only know about the single base folder.

> If a scan finds nothing, check step 1 before step 2. An unmounted share is an
> empty directory, not an error — Ops shows it as **not mounted**, see
> [Verifying](#verifying).

---

## `ONEIRODEX_LIBRARY_ROOTS` / `ONEIRODEX_LIBRARY_ROOTS`

Pipe-separated list. Each entry is a path, optionally prefixed with a display
label and `=`:

```bash
ONEIRODEX_LIBRARY_ROOTS=NAS ROMs=/mnt/nas/roms|Archive=/mnt/archive/games|/srv/extra
```

| Rule | Detail |
|---|---|
| Separator | `\|` (pipe) — same convention as `ARR_REMOTE_PATH_MAP` |
| Label | Optional `Label=` prefix; cosmetic, names the root in the folder browser. Without one the last path segment is used |
| Path | What **Oneirodex** sees. Inside Docker that is the *container* path, not the host path |
| Limit | 32 roots; entries over 4096 chars are dropped |
| Duplicates | Folded — declaring a path that is already `DATA_FOLDER_GAMES` changes nothing |
| Typos | Dropped, not fatal. A malformed entry never stops the app booting |

Declaring a root does three things:

- It appears in **Admin → Libraries & scans → Scan location** as a folder-browser
  starting point (the picker only renders once there is more than one location).
- Its subtree joins the path allowlist, so scan, download, delete, storage and
  export all accept paths under it.
- It gets its own row in **Admin → Ops** path health, so a share that stops
  being mounted is visible rather than silently empty.

`DATA_FOLDER_GAMES` and the OS base folder (`BASE_FOLDER_POSIX` /
`BASE_FOLDER_WINDOWS`) remain roots without being listed. `ONEIRODEX_LIBRARY_ROOTS`
adds to them; it never replaces them.

---

## Docker / Compose

Docker binds what the kernel already has. It does not mount SMB or NFS for you,
so mount on the **host** first, then bind the host mount point into the
container.

`docker-compose.yml` ships three commented slots:

```yaml
    volumes:
      - "${DATA_FOLDER_GAMES}:/storage:ro"
      - "${LIBRARY_ROOT_2_HOST_PATH}:/storage2:ro"
      - "${LIBRARY_ROOT_3_HOST_PATH}:/storage3:ro"
      - "${LIBRARY_ROOT_4_HOST_PATH}:/storage4:ro"
```

Uncomment the ones you need, then in `.env`:

```bash
LIBRARY_ROOT_2_HOST_PATH=/mnt/user/roms
LIBRARY_ROOT_3_HOST_PATH=/mnt/nas/archive

# Container paths — /storage2, not /mnt/user/roms
# Compose interpolates both keys; ONEIRODEX_ wins inside the app if both are set.
ONEIRODEX_LIBRARY_ROOTS=NAS ROMs=/storage2|Archive=/storage3
ONEIRODEX_LIBRARY_ROOTS=
```

```bash
docker compose up -d
```

**The most common mistake** is putting the host path in `ONEIRODEX_LIBRARY_ROOTS`. The
app runs inside the container and sees `/storage2`. A host path there produces a
root that is configured, listed, and permanently "not mounted".

Mount extra libraries **`:ro`** like `/storage`. Scanning never writes; uploads
go to the library volume.

### Unraid

User shares are already on the host at `/mnt/user/<share>`, so they need no
extra mounting — just another bind:

```yaml
- "/mnt/user/roms:/storage2:ro"
```

Unraid's FUSE layer can miss host-side renames, which matters for
`ONEIRODEX_LIBRARY_WATCH` — see [unraid-deploy.md](unraid-deploy.md). Manual and
scheduled scans are unaffected.

---

## Linux host

### SMB / CIFS

```bash
sudo apt install cifs-utils          # or dnf/pacman equivalent
sudo mkdir -p /mnt/nas/roms
```

Keep credentials out of `/etc/fstab` — put them in a root-only file:

```bash
sudo install -m 600 /dev/null /etc/oneirodex-nas.cred
sudo tee /etc/oneirodex-nas.cred >/dev/null <<'EOF'
username=oneirodex
password=REPLACE_ME
EOF
```

`/etc/fstab`:

```
//nas.lan/roms  /mnt/nas/roms  cifs  credentials=/etc/oneirodex-nas.cred,uid=oneirodex,gid=oneirodex,ro,vers=3.0,_netdev,nofail,x-systemd.automount  0  0
```

- `uid=`/`gid=` — SMB has no shared user database, so ownership is assigned at
  mount time. Set it to the account Oneirodex runs as or every file reads as
  `root` and the scan gets permission denied.
- `_netdev` + `nofail` — boot does not hang when the NAS is down.
- `x-systemd.automount` — mounts on first access, so a NAS that boots slower
  than the server still works.

```bash
sudo systemctl daemon-reload && sudo mount -a
ls /mnt/nas/roms
```

### NFS

```bash
sudo apt install nfs-common
sudo mkdir -p /mnt/nas/games
```

```
nas.lan:/export/games  /mnt/nas/games  nfs  ro,_netdev,nofail,x-systemd.automount,soft,timeo=100  0  0
```

NFS maps the *numeric* uid/gid, so the account Oneirodex runs as needs a uid the
export grants. `soft,timeo=` matters: a hard mount on a NAS that goes away
blocks the scan thread indefinitely instead of failing.

### Then declare it

```bash
# .env
ONEIRODEX_LIBRARY_ROOTS=NAS ROMs=/mnt/nas/roms|NAS Games=/mnt/nas/games
```

Restart Oneirodex (`./startweb.sh`, or `systemctl restart oneirodex`).

---

## macOS host

A share mounted in Finder lands under `/Volumes/<name>` and scans like any local
folder:

```bash
ONEIRODEX_LIBRARY_ROOTS=NAS ROMs=/Volumes/roms
```

**Finder mounts are per-login-session.** They disappear when you log out, and a
Oneirodex started by `launchd` at boot cannot see them at all. For anything
other than "I'm sitting at this Mac right now", mount from the command line or
via autofs.

One-off:

```bash
mkdir -p ~/mnt/roms
mount_smbfs //oneirodex@nas.lan/roms ~/mnt/roms
```

Persistent, via `/etc/auto_master` + an autofs map:

```bash
# /etc/auto_oneirodex
/-  auto_smb  -nosuid,ro
```

```bash
# append to /etc/auto_master
/-   auto_oneirodex
```

```bash
sudo automount -vc
```

Store the password in the login keychain rather than in the map file, and point
`ONEIRODEX_LIBRARY_ROOTS` at the mount point.

macOS also asks for explicit consent before a background process reads network
volumes or folders like `~/Documents`. If a scan sees an empty folder that is
plainly not empty, grant the terminal (or the `launchd` job) **Full Disk Access**
in System Settings → Privacy & Security.

---

## Windows host

UNC paths work directly — no drive letter needed:

```
ONEIRODEX_LIBRARY_ROOTS=NAS ROMs=\\nas\roms|Archive=E:\archive
```

**Prefer UNC over a mapped drive letter.** A mapped drive belongs to one
interactive user session. Run Oneirodex as a service or scheduled task and `Z:\`
simply does not exist for it, which shows up as a root that is configured and
never mounted. `install-windows.ps1` warns when it spots a mapped drive in
`-LibraryRoots`.

Members who open games from a UNC root with the desktop companion (**Show in
Explorer**, installs, launches) list the share under **Trusted network shares**
in the companion first. It refuses UNC paths to any other share before they
reach the network ([desktop-companion.md](../user/desktop-companion.md#trusted-network-shares-unc-library-roots)).

If the share needs credentials, give the service account persistent access:

```
cmdkey /add:nas /user:nas\oneirodex /pass
```

Run that **as the account Oneirodex runs under** — credentials stored this way
are per-user. Running Oneirodex under `LocalSystem` cannot reach an
authenticated share at all; use a real account instead.

---

## Verifying

1. **Admin → Ops → path health** lists every root. A configured-but-absent
   share shows as *missing*; a mounted one with the wrong owner shows as *not
   readable*. Extra roots are allowed to be read-only, like `/storage`.
2. **Admin → Libraries & scans → Auto Scan.** The **Scan location** picker lists
   every root, with the resolved path under it. A root that is not mounted right
   now is still listed, marked so — hiding it would turn "the NAS is down" into
   "my library vanished".
3. Pick the location, **Browse**, walk to the folder, **Start Scan**.

```bash
# API check, admin session required
curl -s -b cookies.txt http://localhost:5006/api/library_roots | python -m json.tool
```

```json
{
  "ok": true,
  "roots": [
    {"id": "games", "label": "Games", "path": "/storage", "exists": true, "read": true},
    {"id": "nas-roms", "label": "NAS ROMs", "path": "/storage2", "exists": false, "read": false}
  ]
}
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Root listed as "not mounted" | Nothing is mounted at that path | Mount it on the host; in Docker, add the bind and use the **container** path |
| Root missing from the picker | Only one location exists — the picker hides itself | Check `ONEIRODEX_LIBRARY_ROOTS` reached the process: Ops → path health |
| "Access denied — path outside allowed directories" | Scanning a path under no root | Add its root to `ONEIRODEX_LIBRARY_ROOTS` and restart |
| Scan finds zero games in a full folder | Wrong owner on an SMB mount | Set `uid=`/`gid=` to the Oneirodex account and remount |
| Scan hangs, no progress | Hard NFS mount on an unreachable server | Remount `soft,timeo=100` |
| Works interactively, empty as a service | Mapped drive (Windows) or Finder mount (macOS) | Use UNC / autofs — both are per-session otherwise |
| Root vanished after a reboot | Mount was not persisted | `/etc/fstab` with `nofail,x-systemd.automount`, or autofs |

---

## Related

- [docker-compose-deploy.md](docker-compose-deploy.md) — volume sectioning
- [unraid-deploy.md](unraid-deploy.md) — user shares, library root watch
- [install-native.md](install-native.md) — native install on Linux / macOS / Windows
- [../admin/libraries-and-scans.md](../admin/libraries-and-scans.md) — pointing a library at a location
