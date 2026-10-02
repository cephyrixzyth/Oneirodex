# snes9x / genesis_plus_gx — operator notes (not counsel)

> **Doc status:** Active

This is **not legal advice**. Oneirodex’s authors are not your lawyer. These notes collect
**quotes from the upstream licences** (as published on the projects’ own repositories) and
**questions to take to a lawyer** if you host Oneirodex in a setting that might be commercial.

Related: [webretro-cores.md](../runbooks/webretro-cores.md).

## What Oneirodex does

The 24 WebRetro libretro cores are **not in the git tree**. First boot fetches them onto **this
host** (`FETCH_WEBRETRO_CORES_ON_BOOT`, default on). Removal from the repo does **not** settle
what an operator who then runs that fetch is distributing. You are the provisioning party.

Air-gapped: `FETCH_WEBRETRO_CORES_ON_BOOT=false` and `--from-dir`. Browser play stays honest when
a core is missing.

## Quotes (upstream, not restated as our terms)

Read the current files before you rely on a paraphrase. Licences move.

### snes9x (Snes9x Software License)

Source: [snes9xgit/snes9x LICENSE](https://github.com/snes9xgit/snes9x/blob/master/LICENSE)
(libretro port banner also states commercial rights will not be given).

> Permission to use, copy, modify and/or distribute Snes9x in both binary
> and source form, for non-commercial purposes, is hereby granted without
> fee, providing that this license information and copyright notice appear
> with all copies and any derived work.

> Snes9x is freeware for PERSONAL USE only. Commercial users should
> seek permission of the copyright holders first. Commercial use includes,
> but is not limited to, charging money for Snes9x or software derived from
> Snes9x, including Snes9x or derivatives in commercial game bundles, and/or
> using Snes9x as a promotion for your commercial product.

### genesis_plus_gx

Source: [ekeeke/Genesis-Plus-GX LICENSE.txt](https://github.com/ekeeke/Genesis-Plus-GX/blob/HEAD/LICENSE.txt)
(Charles MacDonald / Eke-Eke; portions MAME).

> Redistributions may not be sold, nor may they be used in a commercial
> product or activity.

Debian and other distros treat that clause as **non-free / non-commercial**. That is a packaging
fact, not a conclusion about your install.

## Questions for a lawyer (if you might host commercially)

Take the full current licence texts, this product’s AGPL source offer (`ONEIRODEX_SOURCE_URL`), and a
plain description of *your* deployment. Typical questions:

1. Is a **household Unraid box** used only by family “personal use” / non-commercial under these
   clauses?
2. Does **charging for a managed Oneirodex host** (SaaS, paid NAS appliance, paid remote play)
   make the fetched WASM a “commercial product or activity”?
3. Does **first-boot fetch onto the operator’s disk** change who is the distributor versus
   shipping the WASM inside the Docker image?
4. Are **other cores** in the same WebRetro pack (GPL-2.0 / GPL-3.0 / MPL-2.0) independent of
   these two, or does mixing them on one play page change the analysis?
5. If the answer is “do not ship those two,” what is the operational path — omit `snes9x` and
   `genesis_plus_gx` from the fetch list, or stop offering SNES / Mega Drive in the browser?

Do not treat a GitHub issue, a Discord anecdote, or this file as the answer.

## What this file is not

- Permission from the copyright holders
- A Oneirodex warranty that household use is fine
- Advice to strip the cores and assume the legal question vanished
