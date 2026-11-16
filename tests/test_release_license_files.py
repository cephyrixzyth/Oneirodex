from pathlib import Path

from scripts.check_release_license_files import REQUIRED_FILES, check_release_license_files


ROOT = Path(__file__).resolve().parents[1]


def test_release_license_inventory_passes_for_checkout():
    assert check_release_license_files(ROOT) == []


def test_release_license_inventory_fails_if_emulatorjs_license_is_missing(tmp_path):
    # Copy the small inventory inputs, then prove this required artifact gates.
    for relative in (
        "LICENSE",
        "oneirodex/setup/fonts/OFL.txt",
        "oneirodex/static/vendor/THIRD-PARTY-NOTICES.md",
        "oneirodex/static/vendor/webretro/LICENSE",
        "oneirodex/static/vendor/nostalgist/LICENSE",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())

    problems = check_release_license_files(tmp_path)
    assert problems == [
        "required licence file missing or empty: oneirodex/static/vendor/emulatorjs/LICENSE"
    ]


def test_release_license_inventory_fails_if_pinned_license_changes(tmp_path):
    for relative in REQUIRED_FILES:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    (tmp_path / "oneirodex/static/vendor/emulatorjs/LICENSE").write_text(
        "substituted licence", encoding="utf-8"
    )

    assert "pinned licence digest mismatch: oneirodex/static/vendor/emulatorjs/LICENSE" in (
        check_release_license_files(tmp_path)
    )
