"""
Narrated how-to videos for the docs — one per feature, with an AI voice.

Each section is a **worked example** scripted as steps. A step is a line of
narration plus the thing on screen that line describes. The recorder:

1. synthesises every line first (Microsoft neural voices via `edge-tts`),
   measures each clip, and caches it under `.artifacts/howto-tts/`;
2. records the section in Playwright, holding on each step for at least as
   long as its narration runs, so the voice and the pointer stay together;
3. draws an app-styled title card at the start, an outro card at the end and
   a lower-third caption for every line — in the theme's own tokens, inside
   the page, so any player shows them;
4. muxes the narration onto the recording with the bundled ffmpeg
   (`imageio-ffmpeg`) into an H.264 / AAC `.mp4`, writes a WebVTT track, a
   poster frame and a transcript, and regenerates `howto/README.md`.

Honesty rules carry over from the silent recorder this replaces. A step the
section is *about* is `required` and aborts the section if the UI cannot do
it — no clip is written. An optional step whose affordance is missing is
dropped from both picture and narration rather than narrated over nothing.

Requires a running capture instance (`python scripts/serve_capture.py`):

    python scripts/capture_howto_videos.py               # every section
    python scripts/capture_howto_videos.py library chat  # a subset
    python scripts/capture_howto_videos.py --list

Env: CAPTURE_BASE_URL · CAPTURE_USER · CAPTURE_PASS · CAPTURE_VOICE
(default en-US-AndrewMultilingualNeural) · CAPTURE_KEEP_WEBM=1 to keep the
raw recording next to the mp4.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_common import (  # noqa: E402
    BASE,
    ROOT,
    block_streams,
    caption,
    close_overlays,
    goto,
    install_caption,
    login,
    page_is_healthy,
    settle,
    title_card_html,
)

VIDEO_DIR = ROOT / "docs" / "media" / "video" / "howto"
TTS_CACHE = ROOT / ".artifacts" / "howto-tts"
VOICE = os.environ.get("CAPTURE_VOICE", "en-US-AndrewMultilingualNeural")
VIEWPORT = {"width": 1600, "height": 900}
FPS = 25
KEEP_WEBM = os.environ.get("CAPTURE_KEEP_WEBM") == "1"

# Seconds a line stays on screen beyond the voice, so the picture is never
# yanked away on the last syllable.
TAIL = 0.75


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------

class MissingAffordance(RuntimeError):
    """A section could not do the thing the video exists to demonstrate."""


@dataclass
class Step:
    say: str
    do: Callable | None = None
    hold: float = 0.0          # minimum seconds on this step, voice or not
    required: bool = False     # abort the section if `do` fails
    poster: bool = False       # take the poster frame at the end of this step


@dataclass
class Section:
    name: str
    title: str
    kicker: str                # "Members" / "Admins"
    blurb: str                 # one sentence for the intro card + index
    guide: str                 # docs path the clip sits beside
    steps: list[Step] = field(default_factory=list)


# --------------------------------------------------------------------------
# page actions — small, named, and honest about failure
# --------------------------------------------------------------------------

def nav(path: str, settle_ms: int = 1_000):
    def _do(page):
        close_overlays(page)
        return goto(page, path, settle_ms=settle_ms)
    return _do


def click(selectors, label: str, *, wait_ms: int = 8_000, after_ms: int = 700):
    """Click the first selector that resolves; False if none do."""
    if isinstance(selectors, str):
        selectors = [selectors]

    def _do(page):
        deadline = wait_ms
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=max(deadline, 1_000))
                loc.scroll_into_view_if_needed(timeout=3_000)
                page.wait_for_timeout(250)
                loc.click(timeout=5_000)
                page.wait_for_timeout(after_ms)
                return True
            except Exception:  # noqa: BLE001
                deadline = 1_500
                continue
        print(f"    no affordance for {label}")
        return False
    return _do


def role(role_name: str, name: str, *, exact: bool = True, after_ms: int = 700):
    def _do(page):
        try:
            loc = page.get_by_role(role_name, name=name, exact=exact).first
            loc.wait_for(state="visible", timeout=8_000)
            loc.scroll_into_view_if_needed(timeout=3_000)
            page.wait_for_timeout(250)
            loc.click(timeout=5_000)
            page.wait_for_timeout(after_ms)
            return True
        except Exception:  # noqa: BLE001
            print(f"    no {role_name} named {name!r}")
            return False
    return _do


def scroll(pixels: int, times: int = 1, pause_ms: int = 650):
    def _do(page):
        for _ in range(times):
            page.mouse.wheel(0, pixels)
            page.wait_for_timeout(pause_ms)
        return True
    return _do


def keys(*sequence: str, delay_ms: int = 500):
    """Press keys in order: 'Control+K', 'type:systems', 'Enter', 'wait:800'."""
    def _do(page):
        for k in sequence:
            if k.startswith("type:"):
                page.keyboard.type(k[5:], delay=70)
            elif k.startswith("wait:"):
                page.wait_for_timeout(int(k[5:]))
            else:
                page.keyboard.press(k)
            page.wait_for_timeout(delay_ms)
        return True
    return _do


def fill(selector: str, value: str):
    def _do(page):
        try:
            loc = page.locator(selector).first
            loc.wait_for(state="visible", timeout=6_000)
            loc.fill(value)
            page.wait_for_timeout(500)
            return True
        except Exception:  # noqa: BLE001
            print(f"    cannot fill {selector}")
            return False
    return _do


def slider(selector: str, values: tuple[str, ...], pause_ms: int = 900):
    def _do(page):
        try:
            loc = page.locator(selector).first
            loc.wait_for(state="visible", timeout=6_000)
            for v in values:
                loc.fill(v)
                page.wait_for_timeout(pause_ms)
            return True
        except Exception:  # noqa: BLE001
            print(f"    no slider {selector}")
            return False
    return _do


def hover(selector: str, after_ms: int = 600):
    def _do(page):
        try:
            loc = page.locator(selector).first
            loc.wait_for(state="visible", timeout=6_000)
            loc.hover(timeout=4_000)
            page.wait_for_timeout(after_ms)
            return True
        except Exception:  # noqa: BLE001
            return False
    return _do


def mouse_click(selector: str, label: str, *, after_ms: int = 800):
    """Move the pointer onto an element and click with raw mouse events.

    For controls that only become interactive *under* the pointer (Discover's
    shelf arrows are `pointer-events: none` until the shelf is hovered):
    Playwright's actionability check refuses them, a real hand does not.
    """
    def _do(page):
        try:
            loc = page.locator(selector).first
            box = loc.bounding_box(timeout=6_000)
            if not box:
                raise RuntimeError("no box")
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            page.mouse.move(x - 40, y)
            page.wait_for_timeout(250)
            page.mouse.move(x, y)
            page.wait_for_timeout(350)
            page.mouse.click(x, y)
            page.wait_for_timeout(after_ms)
            return True
        except Exception:  # noqa: BLE001
            print(f"    no affordance for {label}")
            return False
    return _do


def seq(*actions):
    """Run actions in order; the step succeeds only if every one does."""
    def _do(page):
        ok = True
        for a in actions:
            ok = bool(a(page)) and ok
        return ok
    return _do


def dismiss():
    """Close a menu or popover: Escape, then a click on empty page."""
    def _do(page):
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        try:
            page.mouse.click(VIEWPORT["width"] - 60, VIEWPORT["height"] - 60)
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(400)
        return True
    return _do


def just(fn):
    def _do(page):
        fn(page)
        return True
    return _do


def open_preferences():
    """Preferences is a modal off the account menu, not a route."""
    def _do(page):
        if not click('button[aria-label="Account menu"]', "account menu")(page):
            return False
        return click(['a[href="/settings_panel"]', 'a:has-text("Preferences")'], "Preferences",
                     after_ms=1_600)(page)
    return _do


# --------------------------------------------------------------------------
# the sections — narration is the product truth as of 1.0.0
# --------------------------------------------------------------------------

GAME_TILE = 'a[href*="/game_details/"]'

SECTIONS: list[Section] = [
    Section(
        "tour", "Meet Oneirodex", "Overview",
        "A quick lap of the member app — Discover, the catalog, Systems, and the household.",
        "docs/user/getting-started.md",
        [
            Step("Oneirodex is a self-hosted game library for a household. This is the member app, "
                 "and Discover is where it opens.", nav("/discover", 1_800), required=True),
            Step("Shelves surface what is new, what friends are playing, store deals, and "
                 "curated rows an admin arranges.", scroll(380, 2), hold=2),
            Step("Game Catalog is the whole library — every scanned title, with filters, "
                 "badges and play buttons on each tile.", nav("/library", 1_500), required=True, poster=True),
            Step("Systems groups the same library by console family, with a licensed catalog "
                 "behind each console.", nav("/systems", 1_500)),
            Step("Chat, Friends and Notifications make it a household rather than a file share.",
                 role("button", "Chat"), hold=2.5),
            Step("And everything you just saw is one Ctrl-K away from anywhere.",
                 seq(just(close_overlays), keys("Control+K", "wait:900")), hold=1.5),
            Step("The rest of these clips take each of those areas one at a time.",
                 keys("Escape"), hold=1.0),
        ],
    ),
    Section(
        "library", "Find a game in your library", "Members",
        "Filters, segments, tile size and the actions on a tile.",
        "docs/user/library-and-systems.md",
        [
            Step("Game Catalog lists every title Oneirodex has scanned and identified.",
                 nav("/library", 1_500), required=True),
            Step("The segments across the top split games from soft titles, emulators and utilities.",
                 role("button", "Games"), hold=1.2),
            Step("Back to All.", role("button", "All"), hold=0.6),
            Step("Filters opens the full set — library, system, genre, theme, play path, and sort. "
                 "Update, Missing, New and Lang are one-tap chips.",
                 role("button", "Filters"), required=True, hold=2.5, poster=True),
            Step("Type part of a name to narrow the grid as you go.",
                 fill('input[placeholder="Search by title"]', "ca"), hold=1.2),
            Step("Clear it, and close the panel.",
                 seq(fill('input[placeholder="Search by title"]', ""), role("button", "Filters"))),
            Step("Every tile carries a Play button when browser play is available, a system chip, "
                 "and a freshness badge — NEW here, UPDATE or MISSING after later scans.",
                 hover(GAME_TILE), hold=2.5),
            Step("The heart marks a favourite, and the menu holds download, collection and status actions.",
                 click('button[aria-label^="Open actions for"]', "tile menu"), hold=2.2),
            Step("Close the menu, then open a title to read its page.",
                 seq(dismiss(), click(GAME_TILE, "a game tile", after_ms=1_800)), required=True, hold=2),
        ],
    ),
    Section(
        "game-details", "Read a game page", "Members",
        "Download, play, install, versions, saved states and cheats — in one place.",
        "docs/user/library-and-systems.md",
        [
            Step("Open any tile and you land on the game page.",
                 seq(nav("/library", 1_200), click(GAME_TILE, "a game tile", after_ms=1_800)), required=True),
            Step("The header has the cover, size and status chips, and the actions: Download the files, "
                 "Install through the desktop companion, or Play in browser where the system supports it.",
                 hover('a:has-text("Download"), button:has-text("Download")'), hold=3, poster=True),
            Step("Add to collection keeps household lists; Check updates and DLC asks the store side "
                 "for newer versions.", hover('button:has-text("Add to collection")'), hold=2.2),
            Step("Details on the right shows the library folder and playtime. Open path hands the "
                 "folder to the desktop companion.", scroll(300, 1), hold=2),
            Step("Versions lists the base game and every extra Oneirodex has matched.",
                 scroll(320, 1), hold=2),
            Step("Saved states and household cheat files live here too — browser play and the "
                 "companion both read the same ones.", scroll(360, 1), hold=2.5),
        ],
    ),
    Section(
        "discover", "Discover — the storefront", "Members",
        "Shelves, zones, pin and hide, and See all.",
        "docs/user/library-and-systems.md",
        [
            Step("Discover is Oneirodex as a storefront for your own library.",
                 nav("/discover", 1_800), required=True, poster=True),
            Step("Each row is a shelf. New Library Games, Most Downloaded, Curated for you — an admin "
                 "orders them and can add custom ones with dates.", scroll(360, 1), hold=2.2),
            Step("Pin keeps a shelf at the top for you; Hide removes it for your account only.",
                 hover('button.od-shelf__pin'), hold=2),
            Step("Arrows scroll a shelf, and See all opens it as a full page.",
                 mouse_click('button[aria-label^="Scroll"][aria-label$="right"]:not([disabled])', "shelf arrow",
                             after_ms=900), hold=1.5),
            Step("Zones at the top are curated views — New and updated, and Elsewhere for titles "
                 "outside the vault.", seq(scroll(-1200, 1), role("button", "New & updated")), hold=2.5),
            Step("Everything here is your library, arranged — never a store queue.",
                 nav("/discover", 1_200), hold=1.5),
        ],
    ),
    Section(
        "systems", "Systems and set completion", "Members",
        "Console families, the licensed catalog, export packs and DAT completion.",
        "docs/user/library-and-systems.md",
        [
            Step("Systems is the same library grouped by console family.",
                 nav("/systems", 1_600), required=True, poster=True),
            Step("Each console tile shows how many games you hold, whether they run in the browser, "
                 "and a Catalog link to the licensed release list.", scroll(420, 2), hold=2.5),
            Step("Export packs write a gamelist for ES-DE or Pegasus, so other front ends can show "
                 "the same library without moving a file.", scroll(-900, 1), hold=2.5),
            Step("Completion compares your ROM sets against No-Intro and Redump DATs an admin uploads.",
                 nav("/systems/completion", 1_600), hold=2.5),
            Step("Region chips and percentages tell you exactly what is missing per system.",
                 scroll(300, 1), hold=2),
        ],
    ),
    Section(
        "play", "Ways to play", "Members",
        "Browser play, the desktop companion, and Big Picture for the TV.",
        "docs/user/browser-play.md",
        [
            Step("Ways to Play lists every path to actually running a game.",
                 nav("/ways-to-play", 1_600), required=True, poster=True),
            Step("Browser play uses WebRetro for supported consoles — cores are fetched at first boot, "
                 "and cloud saves and cheats ride along.", scroll(300, 1), hold=3),
            Step("The desktop companion installs, launches and updates PC titles; Catalog is browse-only.",
                 scroll(300, 1), hold=2.5),
            Step("On a tile, Play opens the game straight in a new tab.", nav("/library", 1_200), hold=1),
            Step("Play buttons appear only where the system, the core and any BIOS are actually ready — "
                 "no fake Play buttons.", hover('a.od-tile-play'), hold=2.8),
            Step("Playtime keeps the record of what you ran and for how long.",
                 nav("/playtime", 1_400), hold=2),
        ],
    ),
    Section(
        "big-picture", "Big Picture on the TV", "Members",
        "A ten-foot interface driven by a controller or a few keys.",
        "docs/user/browser-play.md",
        [
            Step("Big Picture is the living-room view — large tiles, one focused title, controller-friendly.",
                 nav("/big-picture", 1_800), required=True, poster=True),
            Step("Left and right browse.", keys("ArrowRight", "ArrowRight", delay_ms=700), hold=1),
            Step("Enter or A opens, D downloads, Y brings up friends, and B starts attract mode.",
                 keys("ArrowLeft", delay_ms=700), hold=2.5),
            Step("Escape blurs the focus and Home returns to the first tile.",
                 keys("Home", delay_ms=600), hold=1.5),
        ],
    ),
    Section(
        "chat-spaces", "Chat, rooms and spaces", "Members",
        "Household rooms, reactions and threads, voice, and invite-only spaces.",
        "docs/user/social-and-voice.md",
        [
            Step("Chat slides out over whatever you are doing.",
                 seq(nav("/library", 1_000), role("button", "Chat")), required=True),
            Step("Expand gives it the whole pane.", role("button", "Expand"), hold=1.2, poster=True),
            Step("Rooms are household channels — general, looking for players, whatever you add.",
                 hover('text=looking-for-players'), hold=2),
            Step("Messages take reactions, replies and threads.", hover('button:has-text("Reply")'), hold=2),
            Step("Voice and Screenshare open a LiveKit session for the room when an admin has enabled it.",
                 hover('button:has-text("Voice")'), hold=2.5),
            Step("Switch to another room.", click(['button:has-text("looking-for-players")',
                                                  'text=looking-for-players'], "another room"), hold=1.5),
            Step("Spaces are servers of their own — text and voice channels, household-wide or invite-only. "
                 "Paste an invite code to join one.", hover('input[placeholder="Paste invite code"]'), hold=3),
            Step("Pop out opens chat as its own window, handy on a second screen.",
                 hover('button:has-text("Pop out")'), hold=2),
        ],
    ),
    Section(
        "friends", "Friends and presence", "Members",
        "The friends dock, adding people, and the pop-out companion.",
        "docs/user/social-and-voice.md",
        [
            Step("Friends is a dock, not a page — it opens from the rail and stays put.",
                 seq(nav("/library", 1_000), role("button", "Friends")), required=True, poster=True),
            Step("It shows who in the household is online and what they are playing.",
                 hover('.od-social-dock, [class*="social-dock"]'), hold=2),
            Step("Add someone by username.", fill('input[placeholder="Add friend username"]', "mira"), hold=1.5),
            Step("Pinned keeps the dock open across pages; Pop out makes it an always-on-top "
                 "window with the desktop companion.", hover('button:has-text("Pop out")'), hold=3),
            Step("Chat and Activity jump straight to those surfaces.",
                 seq(fill('input[placeholder="Add friend username"]', ""), hover('a:has-text("Activity")')), hold=1.5),
        ],
    ),
    Section(
        "collections", "Collections, wishlist and favourites", "Members",
        "The lists that organise a library — and Downloads for what you took.",
        "docs/user/library-and-systems.md",
        [
            Step("Collections are named lists you build from any game page or tile menu.",
                 nav("/collections", 1_500), required=True, poster=True),
            Step("Wishlist tracks titles you want — the release calendar and store deals feed it.",
                 nav("/wishlist", 1_400), hold=2),
            Step("Favourites is the heart on a tile, collected.", nav("/favorites", 1_400), hold=1.5),
            Step("Downloads lists what you have taken from the library and the zips still being built.",
                 nav("/downloads", 1_400), hold=2.2),
            Step("Updates is the inbox for new versions and extras that scans find for titles you hold.",
                 nav("/updates", 1_400), hold=2.2),
        ],
    ),
    Section(
        "calendar-news", "Calendar, news and activity", "Members",
        "What is coming, what happened, and what the household did.",
        "docs/user/library-and-systems.md",
        [
            Step("Release calendar is IGDB's schedule, filtered to what you own or wish for. "
                 "List or Month view.", nav("/calendar", 1_600), required=True, poster=True),
            Step("Month lays the same releases on a grid.", role("button", "Month"), hold=1.8),
            Step("News collects store and publisher feeds an admin has turned on.",
                 nav("/news", 1_600), hold=2),
            Step("Activity is the household timeline — scans, downloads, plays and posts.",
                 nav("/activity", 1_400), hold=2),
            Step("Notifications are yours alone: mentions, invites, finished scans.",
                 nav("/notifications", 1_400), hold=2),
        ],
    ),
    Section(
        "preferences", "Themes, rooms, icons and fonts", "Members",
        "Make it yours from the Preferences modal.",
        "docs/user/preferences-themes.md",
        [
            Step("Preferences lives under the account menu.", seq(nav("/library", 1_000), open_preferences()),
                 required=True),
            Step("Library sets your page size and default sort.", hold=1.5),
            Step("Decade rooms are the scenery — a 1980s wood den, a 90s bedroom, an arcade floor. "
                 "Browser play uses the same room.", scroll(260, 1), hold=3, poster=True),
            Step("Colour cabinets are palettes that still sit in a room rather than a flat colour.",
                 scroll(380, 1), hold=2.5),
            Step("Icon packs are independent of the theme — Outline, Filled, Duotone, Pixel, Soft and Mono.",
                 scroll(220, 1), hold=2.5),
            Step("Fonts offer era faces per system; tile size is a continuous slider.",
                 scroll(200, 1), hold=2.5),
            Step("Save, and the whole app takes the new look.", hold=1.2),
        ],
    ),
    Section(
        "command-palette", "The command palette", "Members",
        "Ctrl-K or Cmd-K to search titles and jump anywhere.",
        "docs/user/getting-started.md",
        [
            Step("From any page, press Control K.", seq(nav("/library", 1_000), keys("Control+K", "wait:800")),
                 required=True),
            Step("Empty, it lists everywhere you can go — and, once you have played something, "
                 "your recent titles and household favourites.", hold=2.5),
            Step("Type two letters to search titles and destinations.",
                 keys("type:sys", "wait:800"), hold=1.5, poster=True),
            Step("Enter goes there.", keys("Enter", "wait:1500"), hold=1.5),
        ],
    ),
    Section(
        "help-support", "Help and reporting a problem", "Members",
        "The in-app guide, and Report issue straight to the admin inbox.",
        "docs/user/faq.md",
        [
            Step("Help is the in-app guide — pick a topic and the answer opens underneath.",
                 nav("/help", 1_600), required=True, poster=True),
            Step("Expand all reads it straight through.", role("button", "Expand all"), hold=1.5),
            Step("Topics cover browser play, controllers, cheats, translations and the licence.",
                 scroll(500, 2), hold=2.5),
            Step("Report sends an issue to the admin's Support inbox, and on to GitHub when configured.",
                 nav("/report", 1_400), hold=2.5),
        ],
    ),
    # ---------------------------------------------------------------- admins
    Section(
        "admin-libraries", "Libraries and scans", "Admins",
        "Add a library, point a scan at a folder, watch the job.",
        "docs/admin/libraries-and-scans.md",
        [
            Step("Libraries and scans is where a library begins.", nav("/libraries", 1_800), required=True,
                 poster=True),
            Step("Each library is a platform plus a folder. Select rows to scan, edit, group or delete them.",
                 click('input[aria-label^="Select Free NES"]', "a library row"), hold=2.5),
            Step("Scan chooses a library and a folder — on this box, a NAS share, or any declared scan "
                 "location — and whether games are folders or files.",
                 nav("/scan_management", 1_800), hold=3),
            Step("Options cover missing games, missing images, extras, and HowLongToBeat.",
                 hover('text=Download missing images'), hold=2.2),
            Step("Scan jobs shows every run with progress, and Unmatched holds what could not be identified "
                 "for you to fix by hand.", nav("/scan_management?active_tab=jobs", 1_600), hold=3),
        ],
    ),
    Section(
        "admin-discover", "Shelves and events", "Admins",
        "Arrange Discover: reorder, hide, and add custom shelves with dates.",
        "docs/admin/discover-sections.md",
        [
            Step("Discovery sections controls what members see on Discover.",
                 nav("/admin/discovery_sections", 1_800), required=True, poster=True),
            Step("Drag to reorder. Toggle Visible to hide a built-in shelf without deleting it.",
                 hover('text=Curated for you'), hold=2.5),
            Step("Add shelf creates a custom one — a hand-picked list, or a library, platform or genre filter.",
                 role("button", "Add shelf"), hold=2.5),
            Step("Give it a start and end date and it becomes an event: a seasonal row that appears "
                 "and retires on its own.", hold=2.5),
            Step("Newsletter, Announcements and Attract mode sit alongside it under Content.",
                 seq(keys("Escape"), nav("/admin/announcements", 1_400)), hold=2.2),
        ],
    ),
    Section(
        "admin-ops", "Ops health", "Admins",
        "Is everything healthy — services, queues, companions, the log.",
        "docs/admin/ops-summary.md",
        [
            Step("The admin Dashboard is the at-a-glance board: libraries, games, health, scans, disk.",
                 nav("/admin/dashboard", 2_200), required=True),
            Step("Ops goes deeper — CPU, memory, database, watch folders, and every service with its status.",
                 nav("/admin/ops", 2_600), required=True, poster=True),
            Step("Tiles resize and the layout is yours; Reset layout puts it back.",
                 hover('button:has-text("Reset layout")'), hold=2),
            Step("Services shows LiveKit, the malware scanner, companions and queues.", scroll(420, 1), hold=2.5),
            Step("The recent log is filterable by level, type and text, and Full log opens the whole thing.",
                 scroll(500, 1), hold=2.5),
            Step("The same numbers are on slash pulse and slash awake for your monitoring.", hold=2),
        ],
    ),
    Section(
        "admin-users", "Users, invites and support", "Admins",
        "Household membership, invite links, roles and the support inbox.",
        "docs/admin/support-inbox.md",
        [
            Step("Users lists every member with their role — admin, librarian, member or child.",
                 nav("/admin/users", 1_800), required=True, poster=True),
            Step("Invites are how people join: generate a link, set its quota, hand it over.",
                 nav("/admin/invites", 1_600), hold=2.5),
            Step("Whitelist pre-approves addresses when registration is open.", nav("/admin/whitelist", 1_400), hold=2),
            Step("Support inbox receives what members send from Report, and can mirror to GitHub Issues.",
                 nav("/admin/support", 1_600), hold=2.5),
        ],
    ),
    Section(
        "admin-settings", "Settings, features and integrations", "Admins",
        "Server settings, module toggles, metadata providers, SSO.",
        "docs/admin/settings-modules.md",
        [
            Step("Settings is the index — library and matching, play and emulation, presentation, extend.",
                 nav("/admin/settings", 1_800), required=True, poster=True),
            Step("Features toggles whole modules: arr, AI assist, VR browse, free games, remote play.",
                 nav("/admin/features", 1_800), hold=2.5),
            Step("Integrations holds the keys — IGDB, SteamGridDB, RetroAchievements, email, and OIDC "
                 "single sign-on, which stays off until you turn it on.", nav("/admin/integrations", 1_800), hold=3),
            Step("Themes uploads packs and resets shipped defaults after a deploy; picking a look is per member.",
                 nav("/admin/themes", 1_600), hold=2.5),
            Step("Emulator profiles map cores and BIOS per system, and say honestly what can run.",
                 nav("/admin/emulator_profiles", 1_600), hold=2.5),
        ],
    ),
    Section(
        "admin-art", "Art studio and extensions", "Admins",
        "Covers without a cloud, the image queue, and reference sets.",
        "docs/admin/theme-fonts-and-images.md",
        [
            Step("Art studio paints a cover from a title — motifs, bezels, initials — with a local renderer. "
                 "No cloud AI.", nav("/admin/art_studio", 1_800), required=True),
            Step("Type a name and the preview updates.", fill('input[placeholder="e.g. Chrono Trigger"]', "Cascade Seven"),
                 hold=2.5, poster=True),
            Step("Generate writes the full pack; Pick and queue fetches SteamGridDB or IGDB art instead.",
                 hover('button:has-text("Generate pack")'), hold=2.5),
            Step("Backup and stock keeps fallbacks, and System marks holds a badge per console.",
                 click(['[role="tab"]:has-text("System marks")', 'button:has-text("System marks")',
                        'a:has-text("System marks")'], "System marks tab"), hold=2.2),
            Step("Extensions lists library extensions — DLC, patches, translations — and Reference sets "
                 "take your DAT uploads.", nav("/admin/extensions", 1_600), hold=2.5),
        ],
    ),
]


# --------------------------------------------------------------------------
# narration
# --------------------------------------------------------------------------

def _ffmpeg() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _clip_path(text: str) -> Path:
    key = hashlib.sha1(f"{VOICE}|{text}".encode("utf-8")).hexdigest()[:20]
    return TTS_CACHE / f"{key}.mp3"


async def _synth_all(lines: list[str]) -> None:
    import edge_tts

    TTS_CACHE.mkdir(parents=True, exist_ok=True)
    todo = [t for t in dict.fromkeys(lines) if not _clip_path(t).exists()]
    if not todo:
        return
    print(f"  tts: synthesising {len(todo)} line(s) with {VOICE}")
    # One socket at a time with backoff: the service is a public endpoint,
    # and a burst of parallel connections has failed DNS resolution here.
    sem = asyncio.Semaphore(2)

    async def one(text: str) -> None:
        async with sem:
            out = _clip_path(text)
            tmp = out.with_suffix(".part")
            last: Exception | None = None
            for attempt in range(5):
                try:
                    await edge_tts.Communicate(text, VOICE, rate="+2%").save(str(tmp))
                    tmp.replace(out)
                    return
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    await asyncio.sleep(1.5 * (2 ** attempt))
            raise RuntimeError(f"tts failed after retries for {text[:50]!r}: {last}")

    await asyncio.gather(*(one(t) for t in todo))


def _duration(mp3: Path) -> float:
    wav = mp3.with_suffix(".wav")
    if not wav.exists():
        subprocess.run([_ffmpeg(), "-v", "error", "-y", "-i", str(mp3), str(wav)], check=True)
    with wave.open(str(wav)) as w:
        return w.getnframes() / float(w.getframerate())


def prepare_narration(sections: list[Section]) -> dict[str, tuple[Path, float]]:
    lines: list[str] = []
    for s in sections:
        lines.append(_intro_line(s))
        lines.extend(st.say for st in s.steps)
        lines.append(_outro_line(s))
    asyncio.run(_synth_all(lines))
    return {t: (_clip_path(t), _duration(_clip_path(t))) for t in dict.fromkeys(lines)}


def _intro_line(s: Section) -> str:
    return f"{s.title}. {s.blurb}"


def _outro_line(s: Section) -> str:
    return f"That is {s.title.lower()}. The written guide is in the docs folder, at {s.guide}."


# --------------------------------------------------------------------------
# recording
# --------------------------------------------------------------------------

@dataclass
class Cue:
    start: float
    text: str
    clip: Path
    dur: float


def record(pw, section: Section, voices: dict[str, tuple[Path, float]], index: int, total: int) -> dict | None:
    """Record one section. Returns the index entry, or None when it failed."""
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    browser = pw.chromium.launch(headless=True)

    # Log in outside the recorded context so the clip starts on the card,
    # not on the login form.
    auth = browser.new_context(viewport=VIEWPORT)
    block_streams(auth)
    p0 = auth.new_page()
    if not login(p0):
        print(f"    {section.name}: login failed, no video written")
        auth.close()
        browser.close()
        return None
    state = auth.storage_state()
    auth.close()

    context = browser.new_context(
        viewport=VIEWPORT,
        storage_state=state,
        record_video_dir=str(VIDEO_DIR / ".rec"),
        record_video_size=VIEWPORT,
    )
    block_streams(context)
    install_caption(context)
    page = context.new_page()
    page.set_default_timeout(15_000)
    t0 = time.monotonic()

    def now() -> float:
        return time.monotonic() - t0

    def hold_until(target: float) -> None:
        remaining = target - now()
        if remaining > 0:
            page.wait_for_timeout(int(remaining * 1000))

    cues: list[Cue] = []
    poster: Path | None = None
    ok = False
    try:
        # Intro card.
        intro = _intro_line(section)
        page.set_content(title_card_html(section.kicker, section.title, section.blurb,
                                         number=f"{index:02d} / {total:02d}"))
        page.wait_for_timeout(400)
        clip, dur = voices[intro]
        cues.append(Cue(now(), intro, clip, dur))
        hold_until(cues[-1].start + dur + 0.6)

        for step in section.steps:
            start = now()
            caption(page, step.say)
            done = True
            if step.do is not None:
                try:
                    done = bool(step.do(page))
                except Exception as exc:  # noqa: BLE001
                    print(f"    step failed: {type(exc).__name__}: {str(exc)[:100]}")
                    done = False
            if not done:
                if step.required:
                    raise MissingAffordance(f"{section.name}: {step.say[:60]}…")
                # Optional and missing: say nothing about it, move on.
                caption(page, "")
                continue
            # The action may have navigated; the caption element is re-created
            # on the new document, so set it again.
            caption(page, step.say)
            clip, dur = voices[step.say]
            cues.append(Cue(start, step.say, clip, dur))
            hold_until(start + max(dur + TAIL, step.hold))
            if step.poster:
                healthy, why = page_is_healthy(page)
                if healthy:
                    poster = VIDEO_DIR / f"howto-{section.name}.png"
                    caption(page, "")
                    page.wait_for_timeout(250)
                    page.screenshot(path=str(poster), full_page=False)
                    caption(page, step.say)
                else:
                    print(f"    poster skipped: {why}")

        healthy, why = page_is_healthy(page) if not page.url.startswith("about:") else (True, "card")
        if not healthy:
            raise MissingAffordance(f"{section.name}: ended on an unhealthy page ({why})")

        caption(page, "")
        outro = _outro_line(section)
        page.set_content(title_card_html(section.kicker, "Read the guide", section.guide))
        page.wait_for_timeout(300)
        clip, dur = voices[outro]
        cues.append(Cue(now(), outro, clip, dur))
        hold_until(cues[-1].start + dur + 1.2)
        ok = True
    except MissingAffordance as exc:
        print(f"    {section.name}: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"    {section.name}: {type(exc).__name__}: {str(exc)[:160]}")
    finally:
        total_s = now()
        src = Path(page.video.path()) if page.video else None
        context.close()
        browser.close()

    if not ok or src is None or not src.exists():
        if src and src.exists():
            src.unlink()
        if poster and poster.exists():
            poster.unlink()
        return None

    out_mp4 = VIDEO_DIR / f"howto-{section.name}.mp4"
    _mux(src, cues, out_mp4)
    if KEEP_WEBM:
        src.replace(VIDEO_DIR / f"howto-{section.name}.webm")
    else:
        src.unlink()
    _write_vtt(cues, VIDEO_DIR / f"howto-{section.name}.vtt")
    print(f"    video: {out_mp4.relative_to(ROOT)}  ({total_s:.0f}s, {len(cues)} lines)")
    return {
        "name": section.name,
        "title": section.title,
        "kicker": section.kicker,
        "blurb": section.blurb,
        "guide": section.guide,
        "file": out_mp4.name,
        "poster": poster.name if poster else None,
        "vtt": f"howto-{section.name}.vtt",
        "seconds": round(total_s),
        "transcript": [c.text for c in cues],
    }


def _mux(video: Path, cues: list[Cue], out: Path) -> None:
    cmd = [_ffmpeg(), "-v", "error", "-y", "-i", str(video)]
    for c in cues:
        cmd += ["-i", str(c.clip)]
    parts = []
    labels = []
    for i, c in enumerate(cues, start=1):
        ms = max(0, int(c.start * 1000))
        parts.append(f"[{i}]adelay={ms}:all=1[a{i}]")
        labels.append(f"[a{i}]")
    parts.append("".join(labels) + f"amix=inputs={len(cues)}:normalize=0:dropout_transition=0,apad[aout]")
    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", "0:v:0", "-map", "[aout]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-movflags", "+faststart", "-shortest",
        str(out),
    ]
    subprocess.run(cmd, check=True)


def _ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _write_vtt(cues: list[Cue], out: Path) -> None:
    lines = ["WEBVTT", ""]
    for i, c in enumerate(cues, start=1):
        lines += [str(i), f"{_ts(c.start)} --> {_ts(c.start + c.dur)}", c.text, ""]
    out.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# index
# --------------------------------------------------------------------------

README_HEAD = """# How-to videos

One short narrated clip per feature, each a **worked example**: open the
thing, use it, show the result. An AI voice (Microsoft neural, via
`edge-tts`) reads a script that is timed to what is on screen; the same lines
are burned in as a lower-third caption and shipped as a WebVTT track next to
each file, so the clips work with sound off and with a screen reader's
transcript.

Recorded by [`scripts/capture_howto_videos.py`](../../../../scripts/capture_howto_videos.py)
against a local capture instance ([`scripts/serve_capture.py`](../../../../scripts/serve_capture.py))
— see [CAPTURE.md](../../../assets/readme/CAPTURE.md). The prose guides say
*why*; the clip shows *where*.

> GitHub plays `.mp4` files in place: click a poster to open the file page.
"""

README_GAPS = """
## What these clips honestly do not show

The capture instance is seeded with the five **legal free sample ROMs** and
no store keys, so:

- **Related media, screenshots, trailers** — no sample title has any, so the
  popup and the lightbox are not demonstrated. They render only when a game
  actually has entries.
- **Browser play itself** — the WebRetro cores are fetched at first boot and
  the capture box keeps outbound traffic off, so the Play button is shown but
  not pressed.
- **Voice** — LiveKit is off in the capture env; the Voice and Screenshare
  buttons are shown, no session is joined.
- **IGDB metadata, release dates, store deals in Discover** — whatever the
  instance could fetch without keys is what you see; an empty calendar or
  news page is the honest state of a keyless install.
- **Fonts** — the picker appears, but the era faces switch visibly only where
  the operator has installed them.

These are gaps in the *sample data*, not in the product. They are listed so
nobody re-records expecting different footage, and so no clip is ever staged
with invented content to fill them.

## Re-recording

```bash
python scripts/serve_capture.py                 # bring up the capture instance
python scripts/capture_howto_videos.py          # all sections
python scripts/capture_howto_videos.py library chat-spaces   # just these
```

A section whose UI cannot do what it is about writes **no file at all**
rather than a clip that narrates over nothing. Voice: `CAPTURE_VOICE`
(any `edge-tts --list-voices` name).
"""


def write_index(entries: list[dict]) -> None:
    index_path = VIDEO_DIR / "index.json"
    existing: dict[str, dict] = {}
    if index_path.exists():
        try:
            existing = {e["name"]: e for e in json.loads(index_path.read_text(encoding="utf-8"))}
        except Exception:  # noqa: BLE001
            existing = {}
    for e in entries:
        existing[e["name"]] = e
    ordered = [existing[s.name] for s in SECTIONS if s.name in existing]
    index_path.write_text(json.dumps(ordered, indent=2), encoding="utf-8")

    def table(kicker_filter):
        rows = ["| | Video | Shows | Guide |", "|---|---|---|---|"]
        for e in ordered:
            if e["kicker"] not in kicker_filter:
                continue
            poster = f'<a href="{e["file"]}"><img src="{e["poster"]}" width="220" alt="{e["title"]}" /></a>' if e.get("poster") else ""
            guide_rel = "../../../../" + e["guide"]
            rows.append(f'| {poster} | [`{e["file"]}`]({e["file"]}) · {e["seconds"]}s | **{e["title"]}** — {e["blurb"]} | [{Path(e["guide"]).name}]({guide_rel}) |')
        return "\n".join(rows)

    transcripts = []
    for e in ordered:
        body = "\n".join(f"{i}. {line}" for i, line in enumerate(e["transcript"], start=1))
        transcripts.append(f"<details>\n<summary><strong>{e['title']}</strong> — transcript</summary>\n\n{body}\n\n</details>\n")

    doc = (
        README_HEAD
        + "\n## Overview and members\n\n" + table({"Overview", "Members"})
        + "\n\n## Admins\n\n" + table({"Admins"})
        + "\n\n## Transcripts\n\nEvery line the voice says, in order — the same text as the `.vtt` tracks.\n\n"
        + "\n".join(transcripts)
        + README_GAPS
    )
    (VIDEO_DIR / "README.md").write_text(doc, encoding="utf-8")
    print(f"index: {VIDEO_DIR / 'README.md'}")


# --------------------------------------------------------------------------

def main() -> int:
    args = [a for a in sys.argv[1:]]
    if "--list" in args:
        for s in SECTIONS:
            print(f"{s.name:18} {s.title}")
        return 0
    wanted = {a.lower() for a in args}
    todo = [s for s in SECTIONS if not wanted or s.name in wanted]
    if not todo:
        print("no matching sections; known:", ", ".join(s.name for s in SECTIONS))
        return 2

    print(f"base: {BASE}")
    voices = prepare_narration(todo)
    # Playwright writes each context's raw recording here before it is muxed.
    # A run killed mid-record leaves one behind; sweep rather than ship it.
    rec = VIDEO_DIR / ".rec"
    rec.mkdir(parents=True, exist_ok=True)
    for leftover in rec.glob("*.webm"):
        leftover.unlink()
        print(f"  swept stale recording {leftover.name}")

    done: list[dict] = []
    failed: list[str] = []
    with sync_playwright() as pw:
        for s in todo:
            idx = SECTIONS.index(s) + 1
            print(f"[{s.name}] {s.title}")
            entry = record(pw, s, voices, idx, len(SECTIONS))
            (done.append(entry) if entry else failed.append(s.name))

    for leftover in rec.glob("*.webm"):
        leftover.unlink()
    try:
        rec.rmdir()
    except OSError:
        pass

    if done:
        write_index(done)
    print(f"\nrecorded {len(done)}/{len(todo)} -> {VIDEO_DIR}")
    if failed:
        print("failed:", ", ".join(failed))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
