from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    content = path.read_bytes()
    if path.suffix == ".json":
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


for name, details in MANIFEST["files"].items():
    path = ROOT / name
    assert path.is_file(), f"Missing evidence artifact: {name}"
    assert digest(path) == details["uploaded_sha256_lf_normalized"], f"Hash mismatch: {name}"
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if name.startswith("api-token-"):
        assert parsed["assertions_passed"] is True, name
        assert parsed["error"] is None, name

matrix_info = MANIFEST["matrix"]
matrix_path = ROOT / "route-action-matrix-current-r1970.json.gz"
assert digest(matrix_path) == matrix_info["uploaded_gzip_sha256"]
with gzip.open(matrix_path, "rt", encoding="utf-8") as stream:
    matrix = json.load(stream)
assert matrix["counts"] == matrix_info["counts"]
assert len(matrix["rows"]) == matrix_info["rows"]
assert len(matrix["current_only_operations"]) == matrix_info["current_only_operations"]

r1970 = json.loads((ROOT / "token-ui-fresh-mobile-r1970.json").read_text(encoding="utf-8"))
assert r1970["assertions_passed"] is True
assert all(value is True for value in r1970["cleanup"].values())

r1972 = json.loads((ROOT / "token-ui-lifecycle-r1972-full.json").read_text(encoding="utf-8"))
assert r1972["assertions_passed"] is True
assert r1972["token_lifecycle_actions_match"] is True
assert r1972["functional_assertions_passed"] is True
assert all(value is True for value in r1972["cleanup"].values())
assert r1972["external_egress_blocked"] is True
assert r1972["source_database_written_by_harness"] is False
surface = r1972["known_ui_differences"]["account_dialog_markup_and_visible_surface"]["visible_surface_bounds_xywh"]
assert surface["legacy"] == surface["current"] == [16, 155, 358, 534]

secret_pattern = re.compile(r"(?i)(?<![A-Za-z0-9])(?:gt_[0-9a-f]{8}_[A-Za-z0-9_-]{8,}|(?:ghp|github_pat|sk|xox[baprs])[-_][A-Za-z0-9_-]{16,})(?![A-Za-z0-9])")
local_path_pattern = re.compile(r"(?i)[A-Z]:\\(?:Apps|Users)\\")
for path in ROOT.iterdir():
    if path.suffix == ".json":
        content = path.read_text(encoding="utf-8")
    elif path.name.endswith(".json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            content = stream.read()
    else:
        continue
    assert not secret_pattern.search(content), f"Credential-like value found in {path.name}"
    assert not local_path_pattern.search(content), f"Local absolute path found in {path.name}"

print(
    json.dumps(
        {
            "bundle_valid": True,
            "report_files_verified": len(MANIFEST["files"]),
            "route_rows_verified": len(matrix["rows"]),
            "current_only_operations": len(matrix["current_only_operations"]),
            "r1972_lifecycle_outcomes_match": True,
            "cleanup_verified": True,
            "secret_and_path_scan": "passed",
        },
        indent=2,
    )
)
