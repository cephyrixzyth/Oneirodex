# BYO VR runtime matrix (INSP-41, VR-XR-1…4)

> **Doc status:** Active

**Status:** runbook, v11 H3b. **Scope:** what a household plugs together *around* Oneirodex so a headset seat can play — the OpenXR runtime, the OpenVR adapter, the streamer, the wire. **Oneirodex ships none of it.** It records how a title plays (`vr_compat`, the headset record — [user/controllers-and-vr.md](../user/controllers-and-vr.md)) and deep-links to where the community keeps its profiles; every runtime, adapter, streamer and tweak below is yours to install from its own project, and this page tells you which one does which job. Where a maintained community wiki already explains a step, this page cites it rather than copying it.

## The four layers

| Layer | Job | What fills it | Where Oneirodex touches it |
|---|---|---|---|
| **OpenXR runtime** | The API a modern VR game talks to. Exactly one runtime is *active* per PC at a time. | On Windows: the headset vendor's runtime (SteamVR, Oculus/Meta, WMR, Pico, Varjo) — the active one is set in each vendor's app or in SteamVR → Settings → OpenXR. On Linux: **Monado** or **WiVRn** (the latter is Monado plus a wireless streamer in one), or SteamVR. | The headset record's `runtime: openxr` says the title is an OpenXR title. Nothing else. |
| **OpenVR adapter** | Older titles talk OpenVR (SteamVR's API). On a non-SteamVR runtime they need a translation layer. | **OpenComposite** (Windows and Linux) maps OpenVR calls onto the active OpenXR runtime. On SteamVR itself, none is needed. | `runtime: openvr` on the record says the title is an OpenVR title — plan for SteamVR or an adapter. |
| **Streamer** | Gets frames from the PC to a standalone headset (Quest, Pico) and tracking back. | **Wireless:** the vendor's link app (Meta Quest Link / Air Link), **Virtual Desktop**, **Steam Link** (Quest), **ALVR**, **WiVRn** (Linux). **Wired:** Link over USB, or the USB-NCM route below for the streamers that speak TCP. | The *Plays flat* row uses **Moonlight** to stream a non-VR title to the headset browser — a different tool for a different job. |
| **Tweaks** | Upscaling, fixed foveated rendering, resolution per title. | OpenXR Toolkit (Windows, per-title layer), the streamer's own settings, SteamVR per-app resolution. | Never distributed, never applied by Oneirodex. Notes on a headset record are the place to write down what a title wanted. |

Rule of thumb: pick the **runtime** first (it is decided by your PC's OS and headset), then the **adapter** only if a title needs it, then the **streamer** only if the headset is standalone, then tweak.

## Choosing a runtime

| You have | Runtime | Notes |
|---|---|---|
| Windows PC, SteamVR-native headset (Index, Vive, **PSVR2** via the PC adapter) | SteamVR | It is both the OpenVR and the OpenXR runtime. Set it as the active OpenXR runtime in SteamVR settings. The PSVR2 steps are in [controllers-and-vr.md](../user/controllers-and-vr.md#psvr2-on-a-pc-step-by-step-vr-pc-1). |
| Windows PC, Quest / Pico | The vendor's link app *or* Virtual Desktop / Steam Link as the OpenXR runtime | Each of these can be the active OpenXR runtime; choose one and leave it. Switching per title is the classic cause of "the headset shows the loading grid forever". |
| Linux PC, Quest / Pico | **WiVRn** (Monado + streamer) | The easiest Linux path today: one flatpak, one headset app, one pairing. OpenVR titles then need **OpenComposite** or the Envision-built SteamVR shim. |
| Linux PC, wired headset (Index, Vive) | **Monado** (via Envision) or SteamVR for Linux | Envision builds and configures Monado + OpenComposite per profile; SteamVR on Linux works for many titles but drops hands on some Proton games. |

For any Linux step, the maintained reference is the **Linux VR Adventures wiki (LVRA)** — start there, then come back. This runbook does not restate it.

## The wired USB-NCM link (Quest 2, measured)

A standalone headset streamed over Wi-Fi is at the mercy of the household router. A **USB network link** turns the USB-C cable into a point-to-point Ethernet link the streamer uses instead of Wi-Fi. The measurement that put this on the register: **0.7 ms RTT and ~756 Mbps** on a Quest 2 over a USB-C 3 cable — lower latency and more headroom than any 5 GHz link in the same house.

What it needs, in order:

1. **A USB 3 cable** that carries data (many charge cables do not). The Link-certified cables and any USB 3.x C-to-C or A-to-C data cable qualify.
2. **A streamer that speaks TCP/IP** — ALVR, WiVRn, Virtual Desktop (via its USB option) and Steam Link all can; the vendor Link app uses its own USB protocol and does not need this.
3. **The NCM gadget enabled on the headset.** Developer mode on the headset; then, from the PC, `adb` forwards or the streamer's own "USB connection" toggle, which brings up an `usb0` / RNDIS-NCM interface on both ends. The LVRA wiki keeps the current per-streamer steps (they change with headset firmware); follow the page for your streamer.
4. **Point the streamer at the link address** (typically a `169.254.x.x` or `10.x.x.x` address on the USB interface, not the Wi-Fi one) and turn the headset's Wi-Fi *off* for the session so nothing falls back.
5. **Measure once** — `ping` the headset over the USB interface (sub-millisecond is the sign it is on the wire) and check the streamer's own bitrate readout; then raise the bitrate until artefacts appear and back off one step.

Nothing here is Oneirodex configuration: it is a cable, a headset setting and a streamer option. The *Plays flat* Moonlight path benefits from the same wire.

## Tweaks — as documentation only

| Want | Where | Note |
|---|---|---|
| Upscaling (FSR / NIS) per title | OpenXR Toolkit (Windows) or the streamer's setting | A layer you install yourself; write the title's setting on its headset record `notes` so the next person sees it. |
| Fixed foveated rendering | OpenXR Toolkit; native on some runtimes | Big win on Quest-class streams; visible edge softness on desk titles. |
| Per-title resolution | SteamVR per-application video settings | The one knob that helps most weak GPUs. |

Oneirodex never applies, distributes or bundles any of these, and never injects into a game — the same rule the community-profile row states: a **record and a link**, nothing more.

## Where Oneirodex fits

- **`vr_compat` and the headset record** (`native` / `injector` / `flat`, runtime, profile page, notes) tell a member how a title plays; the librarian writes them from the details page. Runbook: [user/controllers-and-vr.md](../user/controllers-and-vr.md).
- **Ways to play → In a headset** lists the three rows; `/vr` is the large-target library for a headset browser.
- **Big Picture** with a gamepad drives the site from the couch or the SteamVR desktop overlay.
- **Moonlight** to the household PC is the *Plays flat* path from a headset seat; the desktop companion's *Remote play* row points at your Sunshine/Wolf host.

## Related

- [user/controllers-and-vr.md](../user/controllers-and-vr.md) — headsets, PSVR2 steps, `vr_compat`, the headset record
- strategy/headset-vr.md (local-only reference) — the VR seat model and rider R3
- [user/faq.md](../user/faq.md) — *VR / headsets* rows
