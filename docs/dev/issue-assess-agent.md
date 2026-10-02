# Issue assess & fix (shared support workflow)

> **Doc status:** Active

Near-zero standing cost: tickets land on GitHub; maintainers run Cursor skills on demand. No LLM keys inside Flask.

## Flow

1. Teammate opens **Report issue** (`/report`) in the member app.
2. `POST /api/support/tickets` saves a row, fans out admin in-app alerts, and creates a GitHub Issue when `SUPPORT_GITHUB_TOKEN` is set (otherwise `github_sync=skipped`).
3. Maintainer opens the GitHub issue (or admin **Support inbox**).
4. `issue-assess` — triage only (sev, area, repro gaps).
5. `issue-fix` — implement, test, commit/PR. **Never** auto-merge.

Skills: `.claude/skills/issue-assess/` · `.claude/skills/issue-fix/` · locked defaults [agent-locks.md](agent-locks.md)  
Index: [agent-skills.md](agent-skills.md)

## Token-optimized assess prompt (Custom Agent)

```
You are Oneirodex Issue Assess. Triage user reports only; do not fix code unless told "fix".

Expect: title (required); symptom/logs optional (API caps: body ≤2k, logs ≤4k). Also role, deploy, client, onset, URL/API.
Ask ≤3 clarifying Qs if blocked; still give best-effort triage.

Steps: 1-line restatement → sev P0–P3 → area (auth|library|download|webretro|companion|acquire|social|themes|admin|oidc|security) → ≤2 hypotheses → minimal repro → smallest verify cmds → next: need-info|doc|config|code|ops.

Don't: long roadmaps, dump files, claim certainty without evidence, leak secrets.

Output exactly:
### Triage
**One-liner:**
**Sev:** · **Area:**
**Hypothesis:**
**Need from reporter:**
**Repro:**
**Check:**
**Next:**
**Owner hint:**

≤25 lines. Area paths: open .claude/skills/issue-assess/map.md only when needed.
```

## Env

- `SUPPORT_GITHUB_TOKEN` — PAT with `issues:write`
- `SUPPORT_GITHUB_REPO` — default `chrisjrovira/oneirodex`
