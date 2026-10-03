# Admin navigation

> **Doc status:** Active

The admin shell has a left rail (LHN) and a thin top bar (THN). The rule: the
rail says *where you are*, the top bar says *what else is here*.

## Left rail

Seven sections, each with an icon: Dashboard, Libraries & scans, Settings, Content,
Users, Integrations, System. Sections with several pages fold open (caret on the
heading; the fold state is remembered). Every sub-link carries an icon, as in the
member app. The **Member** group (Library, Log out) sits at the bottom.

**Settings** and **Integrations** unfold into four sub-sections each. A
sub-section is one rail row; the pages inside it are *not* in the rail.

| Section | Sub-sections (pages) |
|---|---|
| Settings | **Library & matching** (Server settings, Scan / match policy, ROM reference sets, Quality profiles, Storage) · **Play & emulation** (Emulators, Remote play) · **Presentation** (Themes, Art studio, Detail layout, Attract mode) · **Extend** (AI assist, Plugins & exports) |
| Integrations | **Metadata & art** (IGDB, Artwork & secondary) · **Stores & ownership** (Store connections, Meta / Quest) · **Messaging & identity** (SMTP, OIDC / SSO, Community chat, Chat emoji, LiveKit voice) · **Acquisition** (Arr module, Indexers) |

Each page has one home. The Support inbox is under Users; ES-DE / Pegasus export
is part of Plugins & exports.

## Top bar

On any page inside a Settings or Integrations sub-section, the top bar shows that
sub-section's pages as icon buttons (the current page is highlighted) plus a way
back to the section's overview (**All settings** / **Overview**). The overview
pages, `/admin/settings` and `/admin/integrations`, list every group as rows —
the same layout on both.

## Page layout

Every page uses the same shell (`Page`: title, one-line lede, content) and the
same panel class. Ops (full-bleed board) and Art studio (its own header) are the
documented exceptions. Page-level actions go in the top bar; Save / Apply buttons
stay with their form.

## Dashboard and Ops boards

Widgets can be moved, resized, pinned, hidden and added — see
[ops-summary.md](ops-summary.md).

## For maintainers

Navigation lives in `frontend/admin-app/src/components/navConfig.ts`:
`SETTINGS_GROUPS` and `INTEGRATION_SECTIONS` define the sub-sections, their icons
and pages; the rail, the top bar (`SectionTopNav`), both overview pages, the
command palette (⌘K / Ctrl+K) and section highlighting all read from them, so a
page added there appears everywhere. Glyphs come from the shared
`frontend/shared/src/railIcons.tsx`; `SectionTopNav.test.tsx` fails if a page is
listed twice or names a glyph that does not exist.
