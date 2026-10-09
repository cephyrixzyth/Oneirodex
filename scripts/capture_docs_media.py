"""
Stills for the README and the docs — every member and admin surface.

Requires a running capture instance (`python scripts/serve_capture.py`) and
Playwright Chromium. Writes `docs/media/screenshots/<name>.png` for each
surface and syncs the README slots under `docs/assets/readme/`.

    python scripts/capture_docs_media.py              # everything
    python scripts/capture_docs_media.py library chat # a subset, by name
    python scripts/capture_docs_media.py --list

Every shot passes `page_is_healthy()` first. A surface that renders an error,
comes up empty or loads unstyled is **skipped and the file on disk left
alone**, and the run exits 3 with the list — a run that hit a mid-capture 500
once wrote "Internal Server Error" into the README hero and reported success.
Treat non-zero as "pixels are stale", never as "done".
"""
from __future__ import annotations

import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_common import (  # noqa: E402
    BASE,
    ROOT,
    block_streams,
    close_overlays,
    goto,
    login,
    page_is_healthy,
)

SHOT_DIR = ROOT / "docs" / "media" / "screenshots"
README_ASSETS = ROOT / "docs" / "assets" / "readme"
VIEWPORT = {"width": 1600, "height": 900}


@dataclass
class Shot:
    name: str                       # docs/media/screenshots/<name>.png
    path: str                       # route to open
    prepare: Callable | None = None # get the page into the state to photograph
    full_page: bool = False
    readme: tuple[str, ...] = field(default_factory=tuple)  # README slot filenames
    settle_ms: int = 1_200


# --------------------------------------------------------------------------
# preparers — put a page in the state the shot is about
# --------------------------------------------------------------------------

def _click(page, selector: str, after_ms: int = 700) -> bool:
    try:
        loc = page.locator(selector).first
        loc.wait_for(state="visible", timeout=8_000)
        loc.click(timeout=5_000)
        page.wait_for_timeout(after_ms)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"    prepare: no {selector} ({type(exc).__name__})")
        return False


def _role(page, role: str, name: str, after_ms: int = 700) -> bool:
    try:
        loc = page.get_by_role(role, name=name, exact=True).first
        loc.wait_for(state="visible", timeout=8_000)
        loc.click(timeout=5_000)
        page.wait_for_timeout(after_ms)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"    prepare: no {role} {name!r} ({type(exc).__name__})")
        return False


def prep_filters(page) -> None:
    _role(page, "button", "Filters", after_ms=1_200)


def prep_game(page) -> None:
    _click(page, 'a[href*="/game_details/"]', after_ms=2_200)


def prep_chat(page) -> None:
    _role(page, "button", "Chat", after_ms=1_400)
    _role(page, "button", "Expand", after_ms=1_200)


def prep_friends(page) -> None:
    _role(page, "button", "Friends", after_ms=1_400)


def prep_palette(page) -> None:
    page.keyboard.press("Control+K")
    page.wait_for_timeout(900)


def prep_preferences(page) -> None:
    if _click(page, 'button[aria-label="Account menu"]', after_ms=600):
        _click(page, 'a[href="/settings_panel"]', after_ms=1_800)


def prep_tile_menu(page) -> None:
    _click(page, 'button[aria-label^="Open actions for"]', after_ms=900)


def prep_ops(page) -> None:
    try:
        page.wait_for_selector("text=LiveKit", timeout=15_000)
        page.wait_for_timeout(600)
    except Exception as exc:  # noqa: BLE001
        print("    ops wait:", type(exc).__name__)


def prep_art(page) -> None:
    try:
        page.locator('input[placeholder="e.g. Chrono Trigger"]').first.fill("Cascade Seven")
        page.wait_for_timeout(1_800)
    except Exception as exc:  # noqa: BLE001
        print("    art studio:", type(exc).__name__)


def prep_add_shelf(page) -> None:
    _role(page, "button", "Add shelf", after_ms=1_000)


def prep_integrations_artwork(page) -> None:
    try:
        page.locator("#retroachievements").scroll_into_view_if_needed(timeout=8_000)
        page.wait_for_timeout(600)
    except Exception as exc:  # noqa: BLE001
        print("    integrations artwork:", type(exc).__name__)


# --------------------------------------------------------------------------
# the surfaces
# --------------------------------------------------------------------------

SHOTS: list[Shot] = [
    # ---- member
    Shot("library", "/library", readme=("screenshot-library.png",)),
    Shot("library-filters", "/library", prep_filters, readme=("screenshot-filters.png",)),
    Shot("library-tile-menu", "/library", prep_tile_menu),
    Shot("game-details", "/library", prep_game, readme=("screenshot-game.png",), settle_ms=1_500),
    Shot("game-details-full", "/library", prep_game, full_page=True, settle_ms=1_500),
    Shot("discover", "/discover", readme=("screenshot-discover.png",), settle_ms=5_000),
    Shot("systems-platforms", "/systems", readme=("screenshot-systems.png",), settle_ms=1_800),
    Shot("systems-completion", "/systems/completion", settle_ms=1_800),
    Shot("chat-channels", "/library", prep_chat, readme=("screenshot-chat.png",)),
    Shot("friends-dock", "/library", prep_friends, readme=("screenshot-friends.png",)),
    Shot("command-palette", "/library", prep_palette, readme=("command-palette.png",)),
    Shot("preferences", "/library", prep_preferences, readme=("screenshot-preferences.png",)),
    Shot("big-picture", "/big-picture", readme=("screenshot-big-picture.png",), settle_ms=2_000),
    Shot("ways-to-play", "/ways-to-play", settle_ms=1_600),
    Shot("collections", "/collections"),
    Shot("wishlist", "/wishlist"),
    Shot("favorites", "/favorites"),
    Shot("downloads", "/downloads"),
    Shot("updates", "/updates"),
    Shot("release-calendar", "/calendar", settle_ms=1_800),
    Shot("news-sections", "/news", settle_ms=2_200),
    Shot("activity", "/activity"),
    Shot("notifications", "/notifications"),
    Shot("playtime", "/playtime"),
    Shot("ownership", "/ownership"),
    Shot("acquire", "/acquire"),
    Shot("vr-browse", "/vr"),
    Shot("help", "/help", full_page=False, settle_ms=1_600),
    Shot("report-issue", "/report"),
    Shot("api-tokens", "/tokens"),
    # ---- admin
    Shot("admin-dashboard", "/admin/dashboard", prep_ops, settle_ms=2_500),
    Shot("admin-ops-services", "/admin/ops", prep_ops, readme=("screenshot-admin-ops.png",), settle_ms=2_500),
    Shot("admin-libraries", "/libraries", readme=("screenshot-admin-libraries.png",), settle_ms=2_000),
    Shot("admin-scan", "/scan_management", settle_ms=2_000),
    Shot("admin-image-queue", "/admin/images", settle_ms=2_000),
    Shot("admin-scan-jobs", "/scan_management?active_tab=jobs", settle_ms=2_000),
    Shot("admin-unmatched", "/scan_management?active_tab=unmatched", settle_ms=2_000),
    Shot("admin-discovery-sections", "/admin/discovery_sections", settle_ms=2_000),
    Shot("admin-discovery-add-shelf", "/admin/discovery_sections", prep_add_shelf, settle_ms=2_000),
    Shot("admin-settings", "/admin/settings", full_page=True, settle_ms=1_800),
    Shot("admin-scan-match", "/admin/scan_match", full_page=True, settle_ms=1_800),
    Shot("admin-features", "/admin/features", full_page=True, settle_ms=1_800),
    Shot(
        "admin-integrations",
        "/admin/integrations#artwork",
        prep_integrations_artwork,
        full_page=True,
        settle_ms=1_800,
    ),
    Shot("admin-themes", "/admin/themes", settle_ms=1_800),
    Shot("admin-users", "/admin/users", settle_ms=1_800),
    Shot("admin-invites", "/admin/invites", settle_ms=1_800),
    Shot("admin-support", "/admin/support", settle_ms=1_800),
    Shot("admin-art-studio", "/admin/art_studio", prep_art, readme=("screenshot-art-studio.png",), settle_ms=1_800),
    Shot("admin-emulator-profiles", "/admin/emulator_profiles", settle_ms=1_800),
    Shot("admin-newsletter", "/admin/newsletter", full_page=True, settle_ms=1_800),
    Shot("admin-extensions", "/admin/extensions", settle_ms=1_800),
    Shot("admin-announcements", "/admin/announcements", settle_ms=1_800),
]


def _sync_readme(src: Path, dest_name: str) -> None:
    README_ASSETS.mkdir(parents=True, exist_ok=True)
    dest = README_ASSETS / dest_name
    dest.write_bytes(src.read_bytes())
    print("    readme:", dest.relative_to(ROOT))


def capture(page, shots: list[Shot]) -> list[str]:
    failures: list[str] = []
    for shot in shots:
        print(f"[{shot.name}] {shot.path}")
        close_overlays(page)
        if not goto(page, shot.path, settle_ms=shot.settle_ms):
            failures.append(f"{shot.name} (navigation)")
            continue
        # Global panels survive navigation; a page must not be photographed
        # under one that an earlier shot opened.
        close_overlays(page)
        if shot.prepare is not None:
            try:
                shot.prepare(page)
            except Exception as exc:  # noqa: BLE001
                print(f"    prepare failed: {type(exc).__name__}: {str(exc)[:100]}")
        healthy, why = page_is_healthy(page)
        if not healthy:
            print(f"    SKIP: {why} — existing {shot.name}.png left untouched")
            failures.append(f"{shot.name} ({why})")
            continue
        try:
            SHOT_DIR.mkdir(parents=True, exist_ok=True)
            out = SHOT_DIR / f"{shot.name}.png"
            page.screenshot(path=str(out), full_page=shot.full_page, timeout=20_000)
            print("    shot:", out.relative_to(ROOT))
            for slot in shot.readme:
                _sync_readme(out, slot)
        except Exception as exc:  # noqa: BLE001
            print(f"    shot failed: {type(exc).__name__}")
            failures.append(f"{shot.name} (screenshot)")
        # Leave modals and menus closed for the next surface.
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    return failures


def main() -> int:
    args = sys.argv[1:]
    if "--list" in args:
        for s in SHOTS:
            print(f"{s.name:28} {s.path}")
        return 0
    wanted = {a.lower() for a in args}
    todo = [s for s in SHOTS if not wanted or s.name in wanted]
    if not todo:
        print("no matching shots; known:", ", ".join(s.name for s in SHOTS))
        return 2

    print("base:", BASE)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        block_streams(context)
        page = context.new_page()
        page.set_default_timeout(20_000)
        try:
            if not login(page):
                print("login failed — nothing captured")
                return 1
            failures = capture(page, todo)
        finally:
            context.close()
            browser.close()

    if not wanted:
        for probe in ("pulse", "awake"):
            try:
                with urllib.request.urlopen(f"{BASE}/{probe}", timeout=5) as resp:
                    (SHOT_DIR / f"{probe}.json").write_text(resp.read().decode("utf-8"), encoding="utf-8")
                    print(f"saved {probe}.json")
            except Exception as exc:  # noqa: BLE001
                print(f"{probe} failed:", exc)

    print(f"\ndone: {len(todo) - len(failures)}/{len(todo)} refreshed -> {SHOT_DIR}")
    if failures:
        print("!! not refreshed (pixels stale):")
        for item in failures:
            print("   -", item)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
