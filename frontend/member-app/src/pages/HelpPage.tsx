import { useEffect, useState } from 'react'
import { ContextBar } from '../chrome/ContextBar'
import { RailIcon } from '../chrome/railIcons'
import './HelpPage.css'
import { useShellConfig } from '@oneirodex/ui'

/**
 * Twelve topics is a strip you scroll, not a switcher you read (W29 human
 * report: "help buttons are overflowing"). They collapse to five groups.
 *
 * Grouped rather than merged, deliberately. Merging the twelve into five
 * sections would have folded twelve headings and their summaries into five and
 * — worse — retired ten anchor ids that are linked from elsewhere in the
 * product: `playHonesty.js` sends a blocked Play straight to `/help#browser-play`.
 * Every section keeps its id, its heading and its own copy; only the switcher
 * is shorter, and a group jumps to the first section in it.
 *
 * `tone` is one of the five semantic colours the theme guarantees — accent,
 * info, success, warning, danger (see od-tokens.css). It is not decoration for
 * its own sake: twelve identical grey panels give the eye nothing to navigate
 * by, so a section is found by re-reading every heading. Colour plus a glyph
 * makes "the one about downloads" findable at a glance, and taking both from
 * the token set means every theme and icon pack restyles them for free rather
 * than fighting a palette invented here.
 */
const FAQ_SECTIONS = [
  {
    id: 'getting-started',
    group: 'Start',
    icon: 'discover',
    tone: 'accent',
    title: 'Getting started',
    short: 'Start',
    summary: 'Nav, Cmd+K, details, health checks',
    items: [
      'Top nav: Discover, Game Catalog, Systems, Downloads, Favorites.',
      'Ctrl+K / ⌘K (or Search) opens the command palette. Type two letters to search titles from any page. An empty box shows titles you played or opened, plus household favourites — not store trends.',
      'Discover shelves can be pinned or hidden per account (Rows in the top bar) — Pin and Hide take effect immediately. News See all opens the News page. Genre See all opens a hub (unplayed / newly added / loved) — not a store genre page.',
      'On long scrollable pages, Jump to top / Jump to bottom controls appear bottom-left (hide when the page does not scroll).',
      'More hubs Collections, Wishlist, Ownership, Big Picture, Ways to Play, and related tools.',
      'Ownership registers titles you already own. Steam, GOG, Epic and Amazon sync live when a token is saved; Xbox and PlayStation live sync is opt-in by your operator; Meta Quest and Playnite import a list. Each store shows its state (Linked, Syncing, Reconnect needed…) with what to do next. First-time setup (/welcome) walks through linking, reviewing matches and opening the library filtered to what you own. A matching name is only a suggestion until you confirm it. Never a store download, never a store password.',
      'Account → API tokens for companion secrets (shown once). Paste the full gt_… string — hyphens/underscores inside are normal. Prefer HTTPS copy; on plain HTTP use Copy or select the secret field + Ctrl/⌘C.',
      'Cover → details: breadcrumb Catalog or Systems › genre › title; trailer/screenshot hook beside the summary; modes and perspectives as catalog chips; About when a storyline exists; store requirements/languages only when Steam filled them; More from this developer in the vault. Trailers, Cheats on RetroArch titles (.cht create/upload), Extras & DLC honesty, multi-disc chips, screenshots, download. Admins: ⋮ → Edit / Open path (companion reveal).',
      'Site down? Ask admin for /pulse, /awake, or Ops → Services.',
    ],
  },
  {
    id: 'library',
    group: 'Collection',
    icon: 'library',
    tone: 'info',
    title: 'Game Catalog & signals',
    short: 'Catalog',
    summary: 'Favorites, chips, tiles, trailers',
    items: [
      'Heart a cover; open Favorites from top nav.',
      'One tile per title, not per copy. A game you hold on NES and SNES is one tile; Preview → Available on lists the other systems, and store / trailer marks (Steam / GOG / Epic / YouTube) when the title has them.',
      'A greyed-out Play button still opens: it explains why (missing BIOS, companion-only, catalog-only) instead of sitting dead.',
      'Game Catalog multi-select: checkbox / long-press / Shift+click → Select page · Favorite · Unfavorite · Add to wishlist · Play status · Refresh freshness / Refresh covers (More; librarian+ · max 20) · Clear; Esc clears. Batch toasts report updated/queued / skipped / failed counts.',
      'Discover is split into zones \u2014 For you \u00b7 New & updated \u00b7 Popular here \u00b7 Elsewhere \u00b7 Curated. The strip above the feed opens each one on its own page; the full feed stays below it. A zone only shows up when it has shelves with something in them.',
      'Grid and Discover take arrow keys and a controller D-pad: the whole shelf stack is one tab stop, Left/Right move along a shelf, Up/Down between shelves, Home/End jump to the ends of a shelf and Ctrl+Home/End to the ends of the stack. Arrows only move — Enter opens a title and Space toggles its selection.',
      'Kind views on the catalog bar: All · Games · Soft titles · Emulators · Utilities — one at a time (All shows every kind). Tile badges EXP / TOOL stay short; tooltips Soft title / Utility.',
      'Filters open from the Filters button on the catalog bar (Apply · Clear · Done). Narrow screens use the same popover.',
      'Signals chips: UPDATE · MISSING · NEW · LANG.',
      'MISSING tile badge (top-left) means files were removed from disk - tooltip explains. Filter with the MISSING Signals chip when available.',
      'Tile size: the slider on the top bar. Titles under covers moved to Preferences → Look & density, beside tile size. Preferences (sectioned: Library · Look · Language) also sets items per page (20–1000).',
      'Game Catalog layout: the kind bar ends with the active layout name (Tile · Rows · Grid) — open it to switch. Tile is the cover grid; Rows is a title list that scales with the slider; Grid is Steam-like genre shelves (same Discover row chrome, full tile-size slider). The choice is remembered in this browser. Favorites and News use the same control (News: Card · Grid · RSS).',
      'Trailers empty state is normal without metadata. Details use embeds; YouTube demo when no trailers.',
      'Extras & DLC lists on-server sidecars only - missing folders stay off-server. Discover may show Extras not on the vault for titles you play or favourite.',
      'When watch/scan adds titles, a short toast may appear (Notifications inbox keeps the row). More than five at once collapse to “N notifications”.',
    ],
  },
  {
    id: 'systems',
    group: 'Collection',
    icon: 'systems',
    tone: 'warning',
    title: 'Systems & themes',
    short: 'Systems',
    summary: 'Platform browse and accents',
    items: [
      'Systems tiles filter the library by console/PC. Each tile carries a Browser / Companion / Catalog badge that matches what Play can actually do. More → Ways to Play opens those same paths as catalog filters, plus Systems and VR.',
      'Set completeness (after an admin uploads a No-Intro/Redump DAT) opens from a Systems tile into the missing list. Region, Systems, and Browse library sit in the top bar. Extra DAT regions include Brazil, Korea, Australia, the UK, France, Germany, Spain, and China.',
      'Licensed catalog (Catalog on a console tile) counts IGDB regional releases for that system. Empty cache means not fetched yet — not zero games ever made. Windows/Steam libraries are not in that report.',
      'Tile badges use four corners only (occupied corners; no empty reserved slots) with rounded-square chrome. Signals: VR, UPDATE, MISSING, NEW, LANG (vs Preferences → Preferred game language). No OUT/~ / RELEASE on tiles.',
      'Inside a system, accents follow that family; global search keeps default glass.',
      'Export packs (top of Systems, beside the intro): ES-DE gamelist.xml and Pegasus metadata for other frontends — optional; paths stay portable.',
      'Change themes in Preferences — decade rooms (the place you started) and colour cabinets. Member and admin chrome share the same room scenery as browser play. Theme, icon pack, font and tile size save together. Preferences is the only place a theme is chosen. The change is visible on a normal reload; no hard refresh.',
    ],
  },
  {
    id: 'downloads',
    group: 'Collection',
    icon: 'downloads',
    tone: 'info',
    title: 'Downloads',
    short: 'Downloads',
    summary: 'Zip queue and retention',
    items: [
      'Download on a game page starts a server zip.',
      'Track progress under Downloads. Files stay until you or an admin remove them.',
    ],
  },
  {
    id: 'social',
    group: 'Community',
    icon: 'friends',
    tone: 'success',
    title: 'Social & voice',
    short: 'Social',
    summary: 'Friends, chat, LiveKit',
    items: [
      'Friends pill or More → Friends: stay-open dock. Pop out uses /social-companion only.',
      'Chat pill / More → Chat / Ctrl+K → Chat: left slide-out room (channels · thread · composer with emoji/attach). Expand widens the panel. Voice & Screenshare in the thread header (LiveKit). Archive (creator/librarian) & Leave. Leave on a household room mutes it. /chat deep-links the same panel. No Discord bots/webhooks.',
      'Spaces (the rail left of chat): household space is everyone; invite-only spaces are invisible until you redeem a code. Text and voice channels live under a space — not a Discord bot.',
      'More → Activity for presence and optional LiveKit. More → Notifications: dense unread inbox; alert prefs under Alert preferences.',
      'No Discord bots/webhooks — native chat, optional LiveKit, or BYO Stoat/Matrix.',
    ],
  },
  {
    id: 'updates-calendar',
    group: 'Collection',
    icon: 'calendar',
    tone: 'warning',
    title: 'Updates & calendar',
    short: 'Updates',
    summary: 'Freshness inbox and release window',
    items: [
      'More → Updates: freshness inbox auto-refreshes while the tab is visible; use Refresh for an immediate pull. Search stores and apply packs stay as before (dense rows, less glass card clutter).',
      'Updates also teases upcoming releases; open the full Release calendar for List or Month views (remembered in-browser) plus Ahead/Behind window controls. Month shows each day’s cover art and cycles through them when more than one title lands that day.',
      'More → Calendar is IGDB metadata only (no downloads). Wishlist and Playtime use the same dense More-page rhythm (honest empty/error). Playtime totals sit in the top bar.',
    ],
  },
  {
    id: 'free-games',
    group: 'Community',
    icon: 'news',
    tone: 'success',
    title: 'Free games',
    short: 'Free games',
    summary: 'News claims and ownership sync',
    items: [
      'News (All · Admins · Free now · Headlines) fills the pane; lists scroll inside. Card / Grid / RSS in the top bar changes how Free now and Headlines look. Card and Grid overlay source (bottom-left) and date (bottom-right) on the art, with the title under the image; RSS stays magazine rows. Free claims live under Free now (and `#free-games`). Claim on the store; Sync ownership if linked (Steam / GOG / Epic / Amazon live when a token is saved).',
      'Oneirodex never downloads DRM titles for you.',
      'Opt out under Notifications → Alert preferences.',
    ],
  },
  {
    id: 'translations',
    group: 'Playing',
    icon: 'content',
    tone: 'info',
    title: 'Translations & patches',
    short: 'Patches',
    summary: 'Locale chips and Flips',
    items: [
      'Preferred game language (default en-US) ≠ UI language.',
      'LANG / PATCH chips mark mismatches and curated extras. Apply with Flips; keep a ROM backup.',
      'AI overlay / patch catalog / companion apply only when the operator enables those flags.',
    ],
  },
  {
    id: 'cheats',
    group: 'Playing',
    icon: 'integrations',
    tone: 'warning',
    title: 'Cheats (.cht)',
    short: 'Cheats',
    summary: 'Details create / upload / play',
    items: [
      'Game details → Cheats (RetroArch titles only): New cheat (name + code rows + dialect hint) or upload a RetroArch .cht.',
      'Dialect labels are capability hints (Raw / GG-style / AR-style / GS-style); files always save as .cht.',
      'Browser play: open Play in browser, then pick the file from the play-bar cheat list. Quick Menu may still be needed to enable codes.',
      'Companion stages the same library .cht files before RetroArch; heavy cores prefer companion over the browser FS.',
      'PC / native titles (PCWIN, PCDOS, MAC, OTHER): the Cheats panel is hidden. No RetroArch list and no memory-cheat wand this wave.',
    ],
  },
  {
    id: 'browser-play',
    group: 'Playing',
    icon: 'big-picture',
    tone: 'danger',
    title: 'Browser play & BIOS',
    short: 'Play',
    summary: 'Firmware honesty, extractors, missing paths',
    items: [
      'Some systems need BIOS/firmware on the host before Play in browser works (PS1, Sega CD, Saturn, and other hard rows). Cartridge NES / SNES / N64 / Genesis do not wait on optional add-on files. Details and tiles show a quiet blocker with the server hint - no Download BIOS button.',
      'Admins upload legally obtained firmware under Admin → Emulators, scan a folder of dumps they already hold, or mount a private host BIOS folder. Oneirodex never ships or downloads copyrighted BIOS files.',
      'Browser Play covers NES, SNES, N64, Game Boy family, DS, Virtual Boy, PS1, Genesis family (including SG-1000), Saturn, Atari line, Lynx, Jaguar, WonderSwan, Neo Geo Pocket / Color, Coleco, Vectrex, 3DO, Neo Geo CD, Intellivision, Channel F, and Odyssey 2 — when the operator has provisioned that core. GameCube / Wii / Dreamcast / 3DS / PS2 / Vita play on the desktop companion. PS5 and Xbox Series stay catalog-only. No fake Play button for a core that is not there.',
      'Rewind stays off on heavy cores (N64, PS1, Saturn, Dreamcast, PSP). Picture cycles CRT · Sharp · Soft. Audio is clocked to the emulated system; the player measures your display refresh so 120/144Hz monitors do not run fast.',
      'Compressed ROMs extract on play. Prefer .zip when possible; .rar/.7z need host tools. Failures show the server hint (missing extractor) in the play shell.',
      'The play bar has Pause, Reset, Mute, volume, Save, Load, Rewind, FF, Picture, and Power (Power leaves the game, same as ← Game Catalog). ? opens shortcuts (F2/F3 save/load, hold Right Shift to rewind, F5 fast-forward). An overlay repeats the in-game controls on touch; on a mouse it appears when you move over the play stage.',
      'An optional NES Nostalgist host (admin flag, off by default) still loads household cores and ROMs from this box. It does not yet have the WebRetro save/load/rewind bar.',
      'If a version is Missing on disk, Download is hidden; a 410 path_missing response toasts the backend hint (remove missing versions or restore files).',
    ],
  },
  {
    id: 'controllers-vr',
    group: 'Playing',
    icon: 'vr',
    tone: 'accent',
    title: 'Controllers & VR',
    short: 'Controllers',
    summary: 'Big Picture and headset browse',
    items: [
      'More → Big Picture: A open, X download, B Attract, Y Friends, Esc exit.',
      'VR browse (/vr) is headset-friendly for any seat — not Quest-only.',
      'VR badge sits in the top-left stack; Sense controllers do not drive the website.',
    ],
  },
  {
    id: 'support',
    group: 'Support',
    icon: 'report',
    tone: 'danger',
    title: 'Need help?',
    short: 'Support',
    summary: 'Report and docs',
    items: [
      'More → Report: choose whether something is broken or you have an idea, then a title. Symptom and logs are optional; Context and Logs stay collapsed until expanded.',
      'Ask your admin for docs/user guides, or see the GitHub repo.',
    ],
  },
  {
    // AGPL §13 requires that people using this *over a network* be offered the
    // Corresponding Source "through some standard or customary means". The
    // README said so; nothing in the running app did. This section is where the
    // obligation is actually discharged, which is why the source link is
    // rendered from shellConfig rather than hardcoded — a modified deployment
    // owes its users its own source.
    //
    // It also carries provider attribution: IGDB (Twitch), Giant Bomb and
    // SteamGridDB each ask for it in their API terms, and the member app
    // surfaced their data with none.
    id: 'about',
    group: 'Support',
    icon: 'report',
    tone: 'info',
    title: 'About & licence',
    short: 'About',
    summary: 'Source code, licence, data credits',
    items: [
      'Oneirodex (oh-NY-roh-dex) is free software under the GNU Affero General Public License v3.0. You may run, study, modify and share it.',
      'Running a modified copy as a network service? AGPL §13 means you owe your users that modified source. Admins set ONEIRODEX_SOURCE_URL to point here at their own fork.',
      'The licence covers Oneirodex itself — not the games, ROMs, BIOS or artwork you point it at. The Python package, Docker image, and GitHub repo still use oneirodex until the identifier wave.',
      'Game metadata and artwork come from IGDB (an Amazon company), Giant Bomb, SteamGridDB and store pages, depending on what your admin configured.',
      'Browser play uses WebRetro with libretro emulator cores, provisioned by your admin rather than shipped with Oneirodex. An optional NES Nostalgist host uses those same household cores.',
    ],
    links: [
      { key: 'source', label: 'Source code (AGPL §13)', href: null, fromConfig: 'sourceUrl' },
      {
        key: 'licence',
        label: 'GNU AGPL v3.0',
        href: 'https://www.gnu.org/licenses/agpl-3.0.html',
      },
      { key: 'igdb', label: 'IGDB', href: 'https://www.igdb.com/' },
      { key: 'giantbomb', label: 'Giant Bomb', href: 'https://www.giantbomb.com/' },
      { key: 'steamgriddb', label: 'SteamGridDB', href: 'https://www.steamgriddb.com/' },
    ],
  },
]

/**
 * The switcher's five entries, derived from the sections rather than declared
 * beside them — a group listed here that no section belongs to would render an
 * empty destination, and a section whose group nobody listed would become
 * unreachable. Order follows first appearance, so it matches reading order
 * down the page.
 */
/* Where the page lands with no deep link. Help is reached by someone who is
   stuck, and an index of thirteen closed topics answers nothing — the first
   topic is the one that covers "how do I use this at all", so it is open. */
const DEFAULT_SECTION_ID = 'getting-started'

function sectionById(id: any) {
  return FAQ_SECTIONS.find((section) => section.id === id) || null
}

/* One topic's body: the bullet list, plus the About section's link row. */
function HelpSectionBody({ section, shellConfig }: LooseProps) {
  return (
    <>
      <ul>
        {section.items.map((item: any) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
      {section.links ? (
        <p className="od-help__links">
          {section.links
            // A link whose href comes from config is dropped when that config
            // is empty rather than rendered dead — an offer of source that
            // goes nowhere is worse than none.
            .map((link: any) => ({
              ...link,
              href: link.fromConfig ? shellConfig[link.fromConfig] : link.href,
            }))
            .filter((link: any) => link.href)
            .map((link: any) => (
              <a
                key={link.key}
                className="od-help__link"
                href={link.href}
                target="_blank"
                rel="noopener noreferrer"
              >
                {link.label}
              </a>
            ))}
        </p>
      ) : null}
    </>
  )
}

/**
 * Cards on top, one reading pane underneath.
 *
 * This was thirteen full-width accordions stacked down the page. Every topic
 * cost a screen of scroll whether or not you wanted it, opening one pushed the
 * rest below the fold, and the page's own index — the thing you came here to
 * use — was a bar strip five groups wide that jumped you into the middle of
 * that stack. The topics are a *menu*: they belong in a grid you can take in
 * at a glance, and the answer belongs in one place under it that does not move
 * when you change your mind.
 *
 * `readAll` is the escape hatch for the other way people use a help page —
 * straight through, start to finish — and it is one button whose label states
 * the state it will move you to, not a permanent Expand/Collapse pair where
 * one of the two is always a no-op.
 */
export function HelpPage() {
  const shellConfig = useShellConfig() as LooseProps
  const useNewChrome = Boolean(shellConfig.enableNewChrome)

  const [activeId, setActiveId] = useState(() => {
    if (typeof window === 'undefined') return DEFAULT_SECTION_ID
    const hash = window.location.hash.replace(/^#/, '')
    return sectionById(hash) ? hash : DEFAULT_SECTION_ID
  })
  const [readAll, setReadAll] = useState(false)

  useEffect(() => {
    const hash = window.location.hash.replace(/^#/, '')
    if (!hash || !sectionById(hash)) return
    setActiveId(hash)
    // The panel, not the card: a deep link (playHonesty.js sends a blocked
    // Play to `/help#browser-play`) is asking for the answer, and scrolling to
    // the card would leave the answer below the fold.
    document.getElementById('od-help-panel')?.scrollIntoView?.({ block: 'start' })
  }, [])

  function selectSection(id: any) {
    if (!sectionById(id)) return
    setActiveId(id)
    // Choosing a card while reading straight through means "just this one".
    setReadAll(false)
  }

  const activeSection = sectionById(activeId) || FAQ_SECTIONS[0]
  const foldLabel = readAll ? 'Collapse all' : 'Expand all'

  const foldButton = (className: any) => (
    <button
      type="button"
      className={className}
      aria-pressed={readAll}
      onClick={() => setReadAll((on) => !on)}
    >
      {foldLabel}
    </button>
  )

  return (
    <>
      {useNewChrome ? (
        <ContextBar
          /* One control on the bar, and it is the only one this page needs.
             The five group chips it replaces jumped into a stack that no
             longer exists — the card grid *is* the index now, and it is on
             the page where a member can see all thirteen topics at once
             rather than five collapsed names in the chrome. The "N of 13
             open" read-out went with them: with one pane open at a time the
             number is always 1, and it was never something to act on. */
          actions={
            <div className="od-seg" role="group" aria-label="Help">
              {foldButton('od-seg__item')}
            </div>
          }
        />
      ) : null}
      <div className="od-more-page od-help">
        {/* Not `od-page-header`: that block is deliberately collapsed under the
          v2 chrome because the bar already names the page. Help is the one page
          where the name is not the point — a member arrives here stuck, and the
          first thing on screen should say what this page can do for them and
          how it is organised. So it is its own banner, and it says something the
          bar does not. */}
        {useNewChrome ? (
          <header className="od-help__hero">
            <span className="od-help__hero-mark" aria-hidden="true">
              <RailIcon name="help" size={26} />
            </span>
            <div className="od-help__hero-copy">
              <h1 className="od-help__hero-title">How Oneirodex works</h1>
              <p className="od-help__hero-lede">
                Pick a topic — the answer opens underneath. Expand all in the bar above reads the
                whole guide straight through.
              </p>
            </div>
          </header>
        ) : null}
        {useNewChrome ? null : (
          <>
            <div className="od-page-header">
              <h1>Help</h1>
            </div>
            <p className="od-more-page__lede">
              Short answers for the member library. Pick a topic; the answer opens underneath.
            </p>

            {/* Classic chrome has no bar to put the control in, so it keeps a
              toolbar — the same single toggle, not a pair. */}
            <div className="od-help__toolbar">{foldButton('od-btn od-btn--ghost')}</div>
          </>
        )}

        {/* The index. Thirteen cards, each carrying its tone and glyph, so a
          topic is found by looking rather than by reading every heading in a
          column. `aria-pressed` rather than a tablist: the panel below is a
          region of the page that these cards change, and a member can still
          reach it by scrolling past them. */}
        <div className="od-help__cards" role="group" aria-label="Help topics">
          {FAQ_SECTIONS.map((section) => {
            const selected = !readAll && section.id === activeSection.id
            return (
              <button
                key={section.id}
                type="button"
                data-tone={section.tone}
                className={`od-help__card${selected ? ' is-selected' : ''}`}
                aria-pressed={selected}
                onClick={() => selectSection(section.id)}
              >
                <span className="od-help__card-mark" aria-hidden="true">
                  <RailIcon name={section.icon} size={18} />
                </span>
                {/* Title only. The summary is not dropped — it renders in the
                  reading pane below once the card is opened
                  (`od-help__section-summary`), which is where it is actually
                  read. On the card it was fourteen lines of subtext competing
                  with the fourteen titles that are the index. */}
                <span className="od-help__card-copy">
                  <span className="od-help__card-title">{section.title}</span>
                </span>
              </button>
            )
          })}
        </div>

        {/* The reading pane. One topic, or all of them in order when the fold
          button is on. The section ids stay on the rendered panels so the
          existing deep links (`/help#browser-play`) still land somewhere real
          in both modes. */}
        <div className="od-help__panel" id="od-help-panel">
          {(readAll ? FAQ_SECTIONS : [activeSection]).map((section) => (
            <section
              key={section.id}
              id={section.id}
              data-tone={section.tone}
              className="od-help__section is-open"
            >
              <h2 className="od-help__section-head">
                <span className="od-help__section-mark" aria-hidden="true">
                  <RailIcon name={section.icon} size={18} />
                </span>
                <span className="od-help__section-copy">
                  <span className="od-help__section-title">{section.title}</span>
                  <span className="od-help__section-summary">{section.summary}</span>
                </span>
              </h2>
              <HelpSectionBody section={section} shellConfig={shellConfig} />
            </section>
          ))}
        </div>

        {/* The source offer, on every render of this page rather than only inside
          the About section — AGPL §13 wants it reachable, not hunted for. The
          URL is configuration: a modified deployment must point at its own. */}
        {shellConfig.sourceUrl ? (
          <p className="od-help__footer">
            Oneirodex{shellConfig.appVersion ? ` ${shellConfig.appVersion}` : ''} — free software
            under the{' '}
            <a
              href="https://www.gnu.org/licenses/agpl-3.0.html"
              target="_blank"
              rel="noopener noreferrer"
            >
              GNU AGPL v3.0
            </a>
            .{' '}
            <a href={shellConfig.sourceUrl} target="_blank" rel="noopener noreferrer">
              Get the source code
            </a>
            .
          </p>
        ) : null}
      </div>
    </>
  )
}
