# P3b Full Cutover Implementation Plan

> **Doc status:** Archive

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove remaining GameTheca / `oneirodex` / `.gt-*` / `--gt-*` identifiers; live Unraid runs `oneirodex-*` containers after redeploy.

**Architecture:** Mechanical rename of Python package directory + path/env defaults; CSS token/class prefix `gt`→`od`; Compose/sidecar container names; docs/media scrub. Keep git history (no rewrite). Postgres DB rename on Unraid via `ALTER DATABASE` during cutover so volumes stay attached.

**Tech Stack:** Flask package `oneirodex/`, Docker Compose, theme CSS, admin/member Vite apps, pytest/vitest.

## Scope (locked)

| Area | Action |
|---|---|
| Package dir | `oneirodex/` → `oneirodex/` |
| Imports / paths | `/app/oneirodex` → `/app/oneirodex`; `from oneirodex` → `from oneirodex` |
| CSS | `.gt-*` → `.od-*`; `--gt-*` → `--od-*`; JS/HTML class/id prefixes |
| Compose | All `container_name: oneirodex-*` → `oneirodex-*`; image build tag `oneirodex:*` |
| DB name | Default `POSTGRES_DB=oneirodex`; Unraid `ALTER DATABASE oneirodex RENAME TO oneirodex` |
| Docs/media | Scrub; delete/replace assets that still say Oneirodex |
| Danger phrase | `RESET ONEIRODEX` only (`RESET ONEIRODEX` accepted one release then drop) |

## Tasks

### Task 1: Package directory + Python/config paths
### Task 2: Dockerfile / compose / Unraid scripts
### Task 3: CSS / JSX / HTML / theme JS prefix gt→od
### Task 4: Docs, agent-locks, HelpPage, media scrub
### Task 5: Unraid DB rename + compose pin + rebuild redeploy
### Task 6: Verify /awake, admin Libraries, member Catalog

**Commit policy:** Do not commit unless user says ship; deploy authorized via compose_then_redeploy.
