# The full-suite failures, named

> **Doc status:** Archive

**Run:** 2026-09-16, `main` @ `10aec59e` (+ the three fixes below) · **`pytest tests/`**
**Result:** **42 failed · 4,450 passed · 5 skipped** in 48:34

This file exists because the number had become folklore. `test-harness-2026-09-10.md`
recorded "33 pre-existing failures … newsletter/download/scan-enrichment/secondary-scrapers
test doubles and drift", named none of them, and no ticket was ever filed. Meanwhile
`test-harness-failures.md` still headlines **0 failed** from its 2026-08-12 re-baseline.
Both were true when written; neither is a work list. This one is.

## Where the number moved

| | 2026-08-12 | 2026-09-11 | 2026-09-16 |
|---|---:|---:|---:|
| Failed | 0 | 33 | **42 → 38** |
| Passed | 3,193 | 4,150 | **4,450** |

The tree gained ~300 tests between the last two runs (PRs #77–#112), so the failure
count growing is not by itself a regression signal — but nine of these are new.

## Fixed in this pass (3 of the 42)

| Test | What was actually wrong |
|---|---|
| `test_forms.py::TestFormsInitialization::test_auto_scan_form_initialization`<br>`test_forms.py::TestFormChoices::test_auto_scan_form_scan_mode_choices`<br>`test_forms.py::TestFormChoices::test_scan_folder_form_scan_mode_choices` | PR #112 added the **Auto** scan mode and made it the default; these three assertions still expected `[('folders',…),('files',…)]` and `default='folders'`. The product is right, the tests were stale. |
| `test_chrome_parity.py::test_libraries_scans_views_are_separate_pages` | Asserted `data_toggle='tab'` appears **nowhere** in `admin_manage_scanjobs.html`. But the redesign deliberately kept in-page panes for **Library tools'** own five views while making the *siblings* separate pages. The assertion is now "exactly one toggling strip, and it is the Library tools one". |
| `test_print_lint.py::test_baseline_exists_and_is_sorted` | The A2.3 utils decomposition inserted `oneirodex/utils/clients/images.py` out of order in `print_lint.baseline.json`. Sorted; the baseline was also tightened 592 → **591** (a genuine reduction). |

## The remaining 38, by cause

**None of these files are in the `pytest-core` hand list**, which is why every one of
them survived the PRs that broke them. That is the argument for the marker flip, not a
separate opinion about it.

### Test doubles that outgrew their subject (20)

`Mock()` standing in for rows and clients whose real surface has since grown, so the
double is missing an attribute the code now reads.

- `test_routes_apis_download.py::TestDeleteDownloadRequest::*` (6)
- `test_scan_enrichment_cascade.py::*` (6)
- `test_utils_secondary_scrapers.py::*` (4) — *known pre-existing since at least 2026-09-11*
- `test_utils_unmatched.py::TestHandleDeleteUnmatched*` (2)
- `test_providers_steamgriddb.py::test_fetch_image_mocked` (1)
- `test_rom_archive.py::test_resolve_nested_zip_member` (1)

### Newsletter (6)

`test_routes_admin_ext_newsletter.py::*` — the admin newsletter surface is one of the
Jinja bodies React has not reached (ADR 0007), and the tests assert its older markup
and form flow.

### Assertions about markup that moved (8)

- `test_wave2c_module_ux.py` (2) · `test_routes_admin_ext_settings_shell.py` (1) —
  settings-shell module badges and section deep links
- `test_member_chrome_css.py` (2) — tile hover glow, top-bar cluster outline; both
  describe CSS the UID-054/055 button-language work rewrote
- `test_member_spa_assets.py` (1) — member SPA CSS link
- `test_collections_api_wiring.py` (2) — one of which (`test_newsletter_ckeditor_targets_content_field`)
  is a newsletter assertion living in the wrong file

### Environment-shaped (2)

- `test_checkout_paths.py::test_operator_docs_checkout_is_oneirodex`
- `test_ai_artwork.py::TestGating::test_enabled_but_unconfigured_is_a_clear_error`

### Timing (1)

- `test_scan_job_timing.py::TestScanJobsStatusTimingAndFilters::test_queued_eta_null`

## On the runner (2026-09-17)

CI's `pytest-core` now runs the marker set and carries these as an explicit `--deselect`
list. 31 of the above reproduce there; the rest are integration-marked or fail only here.
Three fail **only** on the runner and are deselected with that reason: `test_admin_spa_assets::test_admin_spa_dist_built`
(the pytest job does not build the SPA), `test_library_roots::…::test_windows_drive_letter_is_not_mistaken_for_a_label`
(Linux path semantics), `test_theme_fonts::TestCatalogue::test_reports_installed_honestly` (no fonts on the runner).
Fixing a test here means also deleting its line from the workflow.

## How to work this list

Each cluster is one sitting, and each needs the same judgement call the 2026-08-07 pass
got wrong in one direction and the 2026-08-12 pass got right: **decide whether the
product moved or the test is describing something real that broke.** Three of the four
fixed above were stale tests; do not assume the rest are.

Watch for the trap recorded in `oneirodex-review-open-findings`: a mocked test can hide
the bug it covers. `TestSendPasswordResetEmail` passed for months while password-reset
mail was dead, because it asserted the broken endpoint name.

## Reproduce

```bash
docker compose -f docker-compose.review.yml up -d db   # container is not always present
python -m pytest tests/ -q -rfE --no-header
```

Full ID list: `git log` this file, or re-run — every failure above is named in full.
If `create_app()` raises `SystemError` about `pydantic-core`, the shared interpreter has
drifted off the pin again: `pip install --no-deps pydantic-core==2.46.5`.

## Related

- [test-harness-2026-09-10.md](../test-harness-2026-09-10.md) — the SAVEPOINT model these run under
- [test-harness-failures.md](test-harness-failures.md) — the 2026-08-12 re-baseline (stale headline)
- `docs/superpowers/plans/2026-09-16-v1-cycle.md` — Phase 2 owns the marker flip
