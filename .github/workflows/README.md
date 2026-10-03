# Workflows

| File | Runs on | What it gates |
|---|---|---|
| [ci-tests.yml](ci-tests.yml) | push + PR to `main` | The **core** pytest subset, member-app / admin-app / desktop vitest, and the two ratchets. Not the whole `tests/` tree — that is local/release-only, so passing CI is not the same as passing the suite. |
| [desktop-build.yml](desktop-build.yml) | `v*` tags + manual (+ path-filtered pushes/PRs) | Tauri desktop client: six unsigned installers (full + thin × Windows / macOS / Linux). A `v*` tag, or a manual run with `release_tag`, attaches them to that GitHub release. Unsigned `.exe` is the supported path — see [desktop-code-signing.md](../../docs/runbooks/desktop-code-signing.md). |

## There is no codeql.yml (retired 2026-08-24)

GitHub's stock CodeQL starter workflow was committed with the 0.2.0 tree in
`17b3e856` and **failed all 60 of its runs. It never succeeded once.**

The analysis was never the problem — it scanned all 587 Python files and
produced a SARIF report every time. It failed on the last step, uploading
results:

```text
Code scanning is not enabled for this repository.
```

Code scanning on a **private** repository requires GitHub Advanced Security,
which this account does not have (`security_and_analysis` is `null`, and
`GET /repos/.../code-scanning/alerts` answers `403`). The workflow's permissions
were already correct; no configuration makes it pass here. It cost ~6–8 minutes
of Actions time per push to `main` — two jobs, ~4 minutes each — to produce a
report nothing could accept.

Removed rather than silenced. Setting `upload: false` would have turned the
check green over a report nobody reads, and a green check that means nothing is
worse than no check: a permanently red one is why the `test_admin_shell` failure
sat unnoticed on `main` from `e17ca7e1` until someone finally read the run.

**To restore it:** enable GitHub Code Security on the repository (paid for
private repos, free if the repo is ever made public), then re-add the starter
workflow from
<https://github.com/github/codeql-action> — `languages: python,
javascript-typescript`, `build-mode: none`, which is what it was configured for.
Confirm `GET /repos/.../code-scanning/alerts` returns 200 *before* re-adding it,
so the same thing does not happen twice.
