# SD.Next on a Windows GPU box — not the NAS, not the full stack

> **Doc status:** Active

The Unraid/NAS Compose file **never** requests a GPU. Art generation wants one. This household’s accelerator is an **RTX 2080 (8 GB) on the Windows workstation** (the machine that also runs Cursor). Do **not** `compose up` the Oneirodex app/db stack on that PC just to draw covers. Do **not** batch FLUX.1 on this card — 8 GB is too tight; keep FLUX for a 4080-class box.

## Stability Matrix + SwarmUI (this GPU PC)

Installed under `C:\Users\YOUR_USER\Apps` (not the NAS checkout):

| Tool | Path | Notes |
|---|---|---|
| **Stability Matrix** | `C:\Users\YOUR_USER\Apps\StabilityMatrix\StabilityMatrix.exe` | Portable zip from [LykosAI/StabilityMatrix](https://github.com/LykosAI/StabilityMatrix/releases/latest). Use **Package Manager → SwarmUI** for the supported install. |
| **SwarmUI** (source) | `C:\Users\YOUR_USER\Apps\SwarmUI` | `git clone` + `launch-windows.bat` (http://127.0.0.1:7801). First run downloads Comfy + a starter checkpoint — do not pull FLUX fp8 here. |

Oneirodex Art Studio still talks **A1111-compatible** `/sdapi/v1/txt2img`. Keep the SD.Next sidecar on **:7860** as `AI_ARTWORK_URL` until SwarmUI is wired as an engine (not this wave).

Use the sidecar file at the repo root:

```text
docker-compose.artwork-local.yml
```

It starts **only** SD.Next, with an NVIDIA reservation, on port **7860**.

## Before you enable it

```bash
docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi
```

If that fails, Docker Desktop does not see the 2080. Fix the NVIDIA Container Toolkit / WSL2 GPU path first. A reservation on a host with no loaded driver hard-fails container create (`nvml error: driver not loaded`).

Do **not** add `docker-compose.gpu.yml` to the Unraid `.env` `COMPOSE_FILE`. That overlay is for when the *Docker host that runs the app* has the card. The NAS does not.

## Start (GPU PC only)

From this checkout, on the Windows box:

```powershell
docker compose -f docker-compose.artwork-local.yml up -d
```

UI: http://127.0.0.1:7860

**The port is published on loopback only by default.** SD.Next has no login, and anyone who can reach its port can queue generation jobs on this GPU, so `docker-compose.artwork-local.yml` binds `127.0.0.1:7860` unless you set `SDNEXT_HOST_BIND`. Generating from the SD.Next UI on this PC needs nothing more. Serving the NAS needs the opt-in in the next section.

The first pull of `saladtechnologies/sdnext` is large. Models live in the `sdnext_models` volume.

## Point the NAS app at this PC

**1. Open SD.Next to the LAN on this PC (opt-in).** Set `SDNEXT_HOST_BIND` to this PC's LAN IP (preferred: only that adapter listens) before starting, in the shell or in the `.env` next to the compose file, then recreate the container:

```powershell
$env:SDNEXT_HOST_BIND = '192.168.50.42'    # this PC's LAN IP; '0.0.0.0' = every adapter, VPN included
docker compose -f docker-compose.artwork-local.yml up -d --force-recreate
```

> **Upgrading:** before this default existed the file published `7860` on every interface, so the NAS reached it with no setting. After a `git pull`, the next `up -d` / recreate binds loopback only and the NAS gets connection refused until `SDNEXT_HOST_BIND` is set as above. A container that is already running keeps its old binding until it is recreated.

**2. Point the NAS at it.** On the Unraid/NAS `.env` (the running Oneirodex stack):

```text
ENABLE_AI_ARTWORK=true
AI_ARTWORK_ENGINE=a1111
AI_ARTWORK_URL=http://192.168.50.42:7860
```

(Replace the IP if this GPU box’s LAN address changes.)

`docker-compose.yml` must list `ENABLE_AI_ARTWORK` / `AI_ARTWORK_URL` / `AI_ARTWORK_ENGINE` on the **app** service — Compose does not dump the whole `.env` into the container. After editing either file, **rebuild** then recreate — a recreate alone keeps the old image layers (theme CSS / SPA dist stay stale):

```bash
# On Unraid (Compose Manager project root = this checkout):
docker compose --env-file .env build app
docker compose --env-file .env up -d --force-recreate --no-deps app
```

Compose Manager must point at **`_projects/Oneirodex`** (not the empty `_projects/Oneirodex` stub). Drop the `artwork` profile on the NAS when the GPU lives on this workstation.

Allow inbound **TCP 7860** on the Windows firewall (Any profile), with the remote address limited to the NAS's LAN IP rather than Any: SD.Next has no login, so the firewall rule is the access control. If the NAS still cannot reach the URL while `127.0.0.1:7860` works on this PC:

1. **IVPN** — Firewall → Allow LAN (CLI: `ivpn firewall -lan_allow`). Hairpin to this PC’s own LAN IP often still times out; test from the Unraid shell, not from the GPU box.
2. **Portmaster** — turn off **Force Block Incoming Connections** (`filter.blockInbound=false`). Keep Incoming/Service endpoints allowing `192.168.50.0/24`. With Block Incoming on, Unraid cannot open `:7860` even when IVPN Allow LAN is true and Windows Firewall allows the port. After the 2026-08-28 change on this workstation, `http://192.168.50.42:7860/sdapi/v1/sd-models` returns 200 from the LAN IP.

Then retest from the Unraid shell:

```bash
curl -sf http://192.168.50.42:7860/sdapi/v1/sd-models | head
```

Do **not** start `--profile artwork` on the NAS. That profile is the CPU sidecar on the same Compose project; you already have a generator on the LAN.

## Local review stack on this PC

`docker-compose.review.yml` on the GPU workstation sets `ENABLE_AI_ARTWORK=true`, `AI_ARTWORK_URL=http://host.docker.internal:7860`, and `SESSION_COOKIE_SECURE=false` (HTTP on :5006). Start both:

```powershell
docker compose -f docker-compose.artwork-local.yml up -d
docker compose -f docker-compose.review.yml up -d --build
```

`--no-download` does not fetch a checkpoint. Drop a Stable Diffusion 1.5 `.safetensors` into the `sdnext_models` volume (`Stable-diffusion/`) before generating, or the `/sdapi/v1/sd-models` list stays empty.

```powershell
# Download must be exactly 4265146304 bytes (truncated files fail with MetadataIncompleteBuffer):
curl.exe -L --fail -o v1-5-pruned-emaonly.safetensors `
  https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors
# Confirm: (Get-Item .\v1-5-pruned-emaonly.safetensors).Length -eq 4265146304
docker cp .\v1-5-pruned-emaonly.safetensors oneirodex-sdnext-local:/webui/data/models/Stable-diffusion/
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:7860/sdapi/v1/refresh-checkpoints
(Invoke-RestMethod -Uri http://127.0.0.1:7860/sdapi/v1/sd-models).title
```

The review stack reaches SD.Next through `host.docker.internal`; Docker Desktop forwards that to the host's loopback, so it still works with the default loopback bind (checked on this workstation's Docker Desktop, engine 29.8.1) and needs no `SDNEXT_HOST_BIND`.

Compose project name is shared with the review stack (`oneirodex`). Do **not** `compose … --remove-orphans` on one file or you may stop the other stack’s containers.

The backend only POSTs `/sdapi/v1/txt2img`. Nothing leaves the network.

## Seed covers on the local review stack

```powershell
python scripts/fetch-free-roms.py --out $env:TEMP\oneirodex-free-roms
# docker cp each platform folder into oneirodex-review-app:/storage/<platform>
# Admin → create libraries → POST /api/admin/libraries/scan {scan_mode: files, folder}
# Homebrew/test ROMs land in Unmatched — mark as game, then:
# POST /admin/api/artwork/generate { game_uuid, image_type: cover }
```

## Icon packs vs Art Studio

| What | Where |
|---|---|
| Rail / Preferences **glyphs** | SVG under `oneirodex/setup/icon_themes/{pack}/icons/` — `currentColor`, not photos |
| Pack **preview** rasters | `preview.png` in each pack (art-direction samples; chips still use SVG) |
| Game **covers** | Art Studio → this SD.Next URL |
| **Systems hub marks** | Art Studio → **System marks** tab (`#marks`) **Lab** (one platform, editable prompt, preview + attempt log), or `python scripts/generate_system_marks.py --theme default --platform nes`. Batch: `POST /admin/api/art-studio/system-marks/generate`. Files: `static/library/system-marks/<theme>/<platform>.webp`. Prefer the lab until quality is accepted; do not `--all --force`. |

Smoke one mark:

```powershell
$env:ENABLE_AI_ARTWORK = 'true'
$env:AI_ARTWORK_URL = 'http://127.0.0.1:7860'
python scripts/generate_system_marks.py --theme default --platform nes
```

README live screenshots stay captured from a populated instance. Do not invent them with an image generator.

## Stop

```powershell
docker compose -f docker-compose.artwork-local.yml down
```

Related: outbound pairing is still backlog. [docker-compose-deploy.md](docker-compose-deploy.md) § Generated cover art. [container-wont-start.md](container-wont-start.md) § 7.
