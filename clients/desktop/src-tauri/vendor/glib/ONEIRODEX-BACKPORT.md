# GLib 0.18.5 compatibility backport

The Linux Tauri desktop build uses the GTK 3 generation of gtk-rs. Cargo resolves GLib 0.18 from this directory. The published glib 0.18.5 crate has SHA-256 `233daaf6e83ae6a12a52055f568f9d7cf4671dabb78ff9560ab6da230ce00ee5`. The only change to the published crate is the two-line mutable output pointer correction in `src/variant_iter.rs`. The original copyright and MIT license accompany the source.

The version-matched upstream branch still lacked the correction when inspected on November 19, 2026. When the desktop stack accepts a fixed upstream release, remove the Cargo override, regenerate the lockfile, build the Linux companion and rerun its regular tests.

[Upstream correction](https://github.com/gtk-rs/gtk-rs-core/pull/1343) · [RustSec advisory](https://rustsec.org/advisories/RUSTSEC-2024-0429.html)
