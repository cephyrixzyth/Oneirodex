# Exact-image parity evidence bundle — R1967–R1972

This bundle contains the review-relevant artifacts from the local token parity work. It is intended for the independent reviewer to inspect, challenge, and extend. `manifest.json` records each source artifact's SHA-256, cross-platform uploaded-file hashes, and sanitization counts.

## What is included

- R1967 API token lifecycle comparisons, including role, scope, CSRF, malformed input, ownership, and revocation cases.
- R1969 paired token API and desktop/mobile UI evidence.
- R1970 fresh 390×844 route and account-panel evidence, plus the exact route follow-up history.
- The complete R1970 route-action matrix, losslessly compressed after local path and credential scrubbing.
- R1972 full paired account-panel lifecycle results with the original one-time secret omitted.

The matrix still reports **1,545 shared method/path pairs**: 1,545 structurally dispatched, 0 fully behavior-verified, 10 partial, and 1,535 unverified. Current-only operations number 160: 81 non-synthesized, 2 partial, 158 unverified. Structural dispatch coverage is not behavior parity.

## R1972 interpretation

Both images returned 201 for token creation, showed and copied the one-time secret, cleared it on Done, persisted the thin scopes, and returned 200 on revoke with the database row marked revoked. Both also continued to show the revoked token in the account panel and API list. These lifecycle outcomes matched; this does not close the route's other behavior.

The R1972 browser query measured different DOM elements for `role=dialog`: the legacy element is the visible panel, while current marks its full-screen scrim as the dialog. The visible panel outlines in the local screenshots have matching 390×844 viewport bounds on both images: R1970 empty panel `[16, 180, 374, 664)` and R1972 populated panel `[16, 155, 374, 689)`, using x/y/right/bottom coordinates. Treat the visual panel size as matching. Ask the independent reviewer to inspect the dialog role and focus semantics.

The first R1972 harness assertion timed out because it expected the revoked token to disappear from the API list. Follow-up evidence showed DELETE returned 200 and the database row was revoked on both images, while both lists retained the revoked record. The final assertion result is a post-run evaluation of the captured paired evidence; the browser was not rerun after changing only that expectation. `validate_review_bundle.py` checks the recorded evidence and parity conclusions.

The owner approved keeping the current mobile navigation rail closed and `aria-hidden` on 2026-11-06. That is the only owner-disposed UI difference in these runs.

## Validation and privacy

The JSON files parse successfully, and the compressed matrix was decompressed and parsed again; its route counts match the source. Exact image hashes and cleanup results are retained. Raw authorization, CSRF, cookie, secret, password, email, token-hash, and token-prefix string fields are omitted, and machine-local paths are replaced. The full Windows screenshots are not included because their blurred backgrounds still contain the local application page; the panel bounds above were measured from those local captures.

To read the matrix with Python:

```python
import gzip, json

with gzip.open("route-action-matrix-current-r1970.json.gz", "rt", encoding="utf-8") as f:
    matrix = json.load(f)
print(matrix["counts"])
```

Run `python validate_review_bundle.py` from this directory to verify artifact hashes, parse the compressed matrix, and recheck the recorded paired token lifecycle outcomes.

R1972 is a supplemental result after the matrix's R1970 snapshot. Its current owner-approved rail decision and later token lifecycle coverage do not retroactively promote unrelated route rows.
