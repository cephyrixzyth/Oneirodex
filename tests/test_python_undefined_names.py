from scripts.check_undefined_names import undefined_name_errors


def test_production_modules_have_no_pyflakes_undefined_names():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert undefined_name_errors(sorted((root / "oneirodex").rglob("*.py"))) == []


def test_checker_reports_an_undefined_name(tmp_path):
    source = tmp_path / "undefined.py"
    source.write_text("def example():\n    return missing_value\n", encoding="utf-8")

    assert undefined_name_errors([source]) == [
        f"{source}:2:12: undefined name 'missing_value'"
    ]


def test_admin_pilot_annotations_resolve_runtime_typing_names():
    from typing import get_type_hints

    from oneirodex.runtime_native.admin_pilot import create_admin_pilot

    assert "database_scope" in get_type_hints(create_admin_pilot)
