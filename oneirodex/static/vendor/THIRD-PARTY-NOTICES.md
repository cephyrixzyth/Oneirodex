# Third-party notices — vendored browser libraries

Oneirodex itself is AGPL-3.0 ([LICENSE](../../../LICENSE)). The libraries below are **separate
works**, copied into this tree and served to browsers as-is. MIT and BSD both require that the
copyright notice and permission notice travel with the code — they were not present here, which is
what this file fixes.

**Provenance.** Every copyright line below was read out of the banner in the vendored file itself,
not from memory. The two exceptions are marked. Run
[`scripts/fetch-vendor-licenses.sh`](../../../scripts/fetch-vendor-licenses.sh) to drop each
project's canonical `LICENSE` file next to its code as well.

| Library | Version | Licence | Copyright, as stated in the shipped file |
|---|---|---|---|
| [Bootstrap](https://getbootstrap.com/) | 5.3.2 | MIT | Copyright 2011–2023 The Bootstrap Authors |
| [Chart.js](https://www.chartjs.org/) | 4.4.1 | MIT | Chart.js Contributors — **banner stripped** by the jsDelivr build; identifier from upstream `package.json` |
| [Cropper.js](https://fengyuanchen.github.io/cropperjs) | 1.6.1 | MIT | Copyright 2015–present Chen Fengyuan |
| [DataTables](https://datatables.net/) | 1.13.7 | MIT | © 2008–2023 SpryMedia Ltd |
| [DataTables Responsive](https://datatables.net/extensions/responsive/) | 2.5.0 | MIT | © SpryMedia Ltd |
| [jQuery](https://jquery.com/) | 3.7.1 | MIT | © OpenJS Foundation and other contributors |
| [bootstrap-notify](https://github.com/mouse0270/bootstrap-notify) | 0.4.2 | MIT | **No banner** in the vendored copy; identifier from upstream |
| [Sortable](https://github.com/SortableJS/Sortable) | 1.15.2 | MIT | All contributors to Sortable |
| [WebRetro](https://github.com/BinBashBanana/webretro) | 6.5 | MIT | Copyright (c) 2021 BinBashBanana — from [upstream LICENSE](https://github.com/BinBashBanana/webretro/blob/master/LICENSE); the vendored JS has no banner |
| [Nostalgist.js](https://github.com/arianrhodsandlot/nostalgist) | 0.21.1 | MIT | Copyright (c) 2023 arianrhodsandlot — from [upstream LICENSE](https://github.com/arianrhodsandlot/nostalgist/blob/v0.21.1/LICENSE) |

## The MIT licence

Applies to every row above marked MIT, with that row's copyright notice substituted.

```
Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## WebRetro

`webretro/` is the browser-play front end. Two things about it are worth recording:

1. **The front end is MIT.** Upstream
   [LICENSE](https://github.com/BinBashBanana/webretro/blob/master/LICENSE) is MIT, Copyright (c)
   2021 BinBashBanana. A copy sits at [webretro/LICENSE](webretro/LICENSE). The vendored JS still
   has no banner; the identifier comes from that upstream file, not from a comment in the minified
   sources.
2. **The libretro cores are not in this tree.** `webretro/cores/` is gitignored and provisioned at
   first boot — see [cores/README.md](webretro/cores/README.md) and
   `oneirodex/utils/webretro_core_install.py`. They carry GPL-2.0, GPL-3.0 and MPL-2.0 terms, and
   `snes9x` and `genesis_plus_gx` add clauses restricting commercial distribution, so an operator who
   runs the fetch — not this repository — is the party provisioning them.

`webretro/info/` was removed in the same pass. Those five pages were the upstream author's own terms
of service, privacy policy and cookie policy: they described a "legally binding agreement between you
and this Website operator", named a different website as the service, linked to a broken
`http://privacy.html`, and carried Discord links that Oneirodex's own non-goals rule out. Every
deployment was serving them from its own domain. Nothing in Oneirodex linked to them; only the
unreferenced `Info` link in `standalone.html` did, and that link is gone.

## Nostalgist.js

`nostalgist/` is the optional NES launch host (BP-1). The UMD is MIT, Copyright (c) 2023
arianrhodsandlot; a copy sits at [nostalgist/LICENSE](nostalgist/LICENSE). It does **not** fetch
sample ROMs or cores from a CDN in our host: `play.html` points `rom` at same-origin
`/api/downloadrom/<uuid>` and cores at the operator-provisioned WebRetro WASM tree.

## EmulatorJS

`emulatorjs/` holds Oneirodex's play shell (`play.html`, AGPL like the rest of the
app) and the pinned EmulatorJS release fetched during Docker image build. The
engine can be disabled in Admin → Emulators. EmulatorJS is
GPL-3.0 (https://github.com/EmulatorJS/EmulatorJS, Copyright (c) EmulatorJS contributors); its
licence text ships inside that release (`data/LICENSE`) and the libretro cores it bundles carry
their own — use remains subject to those licences, exactly as with the WebRetro cores tree.
The shell fetches nothing from a CDN: ROM over same-origin `/api/downloadrom/<uuid>`, loader
and cores from `emulatorjs/data/` on this origin.

## Not covered here

Front-end npm dependencies (`frontend/*/package.json`) are resolved at build time and are not
vendored into this tree — their licences travel in `node_modules` and in the lockfiles.
