import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Command } from 'cmdk'
import { useLocation, useNavigate } from 'react-router-dom'
import { useShellConfig, useViewer } from '@oneirodex/ui'
import { searchGames } from '../api/collections'
import { fetchPaletteSuggest } from '../api/palette'
import { openPreferencesModal } from '../api/preferences'
import { clearLegacyRecentTitles, mergeSuggestRecent } from '../utils/recentTitles'
import { requestOpenChatPanel } from '../hooks/chatPanelApi'
import { requestOpenSocialCompanion } from '../hooks/socialCompanionApi'
import { getMoreLinks, getPrimaryLinks } from './navConfig'
import './CommandPalette.css'

/**
 * Build unique command entries from nav config + Preferences action.
 * @param {{ isAdmin?: boolean, showTrailers?: boolean, showHelp?: boolean, enableVr?: boolean }} shellConfig
 */
export function buildPaletteCommands(shellConfig: LooseProps = {}) {
  const {
    isAdmin = false,
    showTrailers = false,
    showHelp = false,
    enableVr = false,
    enableActivity = true,
  } = shellConfig

  const seen = new Set()
  const commands: any[] = []

  function push(cmd: any) {
    if (!cmd?.id || seen.has(cmd.id)) return
    seen.add(cmd.id)
    commands.push(cmd)
  }

  for (const link of getPrimaryLinks()) {
    push({
      id: link.id,
      label: link.label,
      to: link.to,
      href: link.href,
      external: Boolean(link.external),
      group: 'Navigate',
    })
  }

  if (isAdmin) {
    push({
      id: 'admin',
      label: 'Admin',
      href: '/admin/dashboard',
      external: true,
      group: 'Navigate',
    })
  }

  for (const link of getMoreLinks({ showTrailers, showHelp, enableVr, enableActivity })) {
    push({
      id: link.id,
      label: link.label,
      to: link.to,
      href: link.href,
      action: link.action,
      external: Boolean(link.external),
      group: 'More',
    })
  }

  push({
    id: 'preferences',
    label: 'Preferences',
    action: 'preferences',
    group: 'Account',
  })
  push({
    id: 'tokens',
    label: 'API tokens',
    to: '/tokens',
    group: 'Account',
  })

  return commands
}

/**
 * True when Cmd+K should prioritize library title search.
 * @param {string} pathname
 */
export function isLibrarySearchRoute(pathname = '') {
  return pathname === '/library' || pathname.startsWith('/library/')
}

/**
 * Ctrl/Cmd+K command palette for primary + More nav jumps and Preferences.
 * Title search runs on every page once two characters are in the box.
 * An empty box shows recently played / opened titles and household favourites.
 */
/**
 * Should this keystroke open the palette and become its first character?
 *
 * "Any key" has to mean *any key the reader meant as typing*, or the feature
 * turns into a trap. Excluded, and why:
 *
 *   - modifier chords (Ctrl/Cmd/Alt): those are shortcuts, not text — Ctrl+C
 *     must stay copy. Shift is allowed, because Shift+A is just "A".
 *   - anything but a single character: Enter, Tab, Escape, arrows and F-keys
 *     all report multi-character `key` values, so one length check covers them.
 *   - space: it scrolls, and a palette that opens on scroll is unusable.
 *   - keystrokes already going somewhere that takes text — an input, textarea,
 *     select, or any contenteditable region. Without this, typing in the
 *     filter box or a chat composer would yank focus away mid-word.
 *
 * Exported for tests: the exclusions are the whole feature, and they are much
 * easier to state as cases than to drive through a rendered palette.
 */
export function typeToSearchKey(event: any) {
  if (event.metaKey || event.ctrlKey || event.altKey) return false
  if (!event.key || event.key.length !== 1 || event.key === ' ') return false

  const target = event.target
  if (!target || typeof target.closest !== 'function') return true
  if (target.isContentEditable) return false
  return !target.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]')
}

export function CommandPalette({ open: openProp, onOpenChange, defaultOpen = false }: LooseProps) {
  const viewer = useViewer()
  const shellConfig = useShellConfig()
  const navigate = useNavigate()
  const location = useLocation()
  const libraryMode = isLibrarySearchRoute(location.pathname)
  const controlled = openProp !== undefined
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen)
  const open = controlled ? openProp : uncontrolledOpen
  const openRef = useRef(open)
  openRef.current = open

  const [query, setQuery] = useState('')
  const [libraryHits, setLibraryHits] = useState<any[]>([])
  const [libraryStatus, setLibraryStatus] = useState('idle') // idle | loading | ready | error
  const [suggest, setSuggest] = useState<{ recent: any[]; popular: any[] }>({
    recent: [],
    popular: [],
  })
  const [suggestStatus, setSuggestStatus] = useState('idle') // idle | loading | ready | error

  const setOpen = useCallback(
    (next: any) => {
      const value = typeof next === 'function' ? next(openRef.current) : next
      if (!controlled) setUncontrolledOpen(value)
      onOpenChange?.(value)
    },
    [controlled, onOpenChange],
  )

  const commands = useMemo(
    () => buildPaletteCommands({ ...shellConfig, isAdmin: viewer.isAdmin }),
    [shellConfig, viewer.isAdmin],
  )

  useEffect(() => {
    function onKeyDown(event: any) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setOpen((prev: any) => !prev)
        return
      }
      // Type-to-search: any printable key opens the palette with that character
      // already in it, so finding a game does not require remembering a
      // shortcut. Deliberately narrow about when it fires — see typeToSearchKey.
      if (!open && typeToSearchKey(event)) {
        event.preventDefault()
        setQuery(event.key)
        setOpen(true)
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, setOpen])

  useEffect(() => {
    if (!open) {
      setQuery('')
      setLibraryHits([])
      setLibraryStatus('idle')
    }
  }, [open])

  useEffect(() => {
    clearLegacyRecentTitles()
    if (!open) {
      setSuggest({ recent: [], popular: [] })
      setSuggestStatus('idle')
      return undefined
    }
    const controller = new AbortController()
    setSuggest({ recent: [], popular: [] })
    setSuggestStatus('loading')
    fetchPaletteSuggest({ signal: controller.signal })
      .then((data) => {
        if (controller.signal.aborted) return
        setSuggest({
          recent: mergeSuggestRecent(data.recent),
          popular: Array.isArray(data.popular) ? data.popular : [],
        })
        setSuggestStatus('ready')
      })
      .catch((err: any) => {
        if (err?.name === 'AbortError') return
        if (controller.signal.aborted) return
        setSuggest({ recent: [], popular: [] })
        setSuggestStatus('error')
      })
    return () => controller.abort()
  }, [open, viewer.userId])

  useEffect(() => {
    if (!open) {
      return undefined
    }
    const trimmed = query.trim()
    if (trimmed.length < 2) {
      setLibraryHits([])
      setLibraryStatus('idle')
      return undefined
    }

    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      setLibraryStatus('loading')
      searchGames(trimmed, { signal: controller.signal, limit: 12 })
        .then((rows) => {
          setLibraryHits(Array.isArray(rows) ? rows : [])
          setLibraryStatus('ready')
        })
        .catch((err: any) => {
          if (err?.name === 'AbortError') return
          setLibraryHits([])
          setLibraryStatus('error')
        })
    }, 220)

    return () => {
      window.clearTimeout(timer)
      controller.abort()
    }
  }, [open, query])

  async function runCommand(cmd: any) {
    setOpen(false)
    if (cmd.action === 'preferences') {
      try {
        await openPreferencesModal()
      } catch {
        window.location.href = '/settings_panel'
      }
      return
    }
    if (cmd.action === 'open-friends') {
      requestOpenSocialCompanion()
      return
    }
    if (cmd.action === 'open-chat') {
      requestOpenChatPanel()
      return
    }
    if (cmd.external || cmd.href) {
      window.location.href = cmd.href
      return
    }
    if (cmd.to) {
      navigate(cmd.to)
    }
  }

  const groups = useMemo(() => {
    const map = new Map()
    for (const cmd of commands) {
      const list = map.get(cmd.group) || []
      list.push(cmd)
      map.set(cmd.group, list)
    }
    return [...map.entries()]
  }, [commands])

  const showLibraryGroup = query.trim().length >= 2
  const showSuggest = query.trim().length < 2
  const recentTiles = showSuggest ? suggest.recent : []
  const popularTiles = showSuggest
    ? suggest.popular.filter((row) => !recentTiles.some((recent) => recent.uuid === row.uuid))
    : []

  function openTitle(hit: any) {
    const uuid = hit?.uuid || hit?.id
    if (!uuid) return
    setOpen(false)
    navigate(`/game_details/${encodeURIComponent(uuid)}`)
  }

  return (
    <Command.Dialog
      open={open}
      onOpenChange={setOpen}
      label="Command palette"
      className="od-cmdk"
      overlayClassName="od-cmdk__overlay"
      contentClassName="od-cmdk__content"
      loop
    >
      <Command.Input
        className="od-cmdk__input"
        placeholder={libraryMode ? 'Search library…' : 'Search titles or pages…'}
        value={query}
        onValueChange={setQuery}
        autoFocus
      />
      <Command.List className="od-cmdk__list">
        <Command.Empty className="od-cmdk__empty">
          {libraryStatus === 'loading'
            ? 'Searching library…'
            : libraryStatus === 'error'
              ? 'Library search failed.'
              : showLibraryGroup && libraryHits.length === 0
                ? 'No matching library titles.'
                : 'No matching commands.'}
        </Command.Empty>

        {showSuggest && suggestStatus === 'error' ? (
          <div className="od-cmdk__empty" role="status">
            Suggestions are unavailable. Title search is still available.
          </div>
        ) : null}

        {recentTiles.length > 0 ? (
          <Command.Group heading="Recent titles" className="od-cmdk__group">
            {recentTiles.map((hit) => {
              const uuid = hit.uuid
              const name = hit.name || 'Untitled'
              return (
                <Command.Item
                  key={`recent-${uuid}`}
                  value={`recent ${name} ${uuid}`}
                  keywords={[name, String(uuid)]}
                  className="od-cmdk__item"
                  onSelect={() => openTitle(hit)}
                >
                  <span className="od-cmdk__item-label">{name}</span>
                  <span className="od-cmdk__item-hint">{hit.hint || 'Played recently'}</span>
                </Command.Item>
              )
            })}
          </Command.Group>
        ) : null}

        {popularTiles.length > 0 ? (
          <Command.Group heading="Popular here" className="od-cmdk__group">
            {popularTiles.map((hit) => {
              const uuid = hit.uuid
              const name = hit.name || 'Untitled'
              return (
                <Command.Item
                  key={`popular-${uuid}`}
                  value={`popular ${name} ${uuid}`}
                  keywords={[name, String(uuid)]}
                  className="od-cmdk__item"
                  onSelect={() => openTitle(hit)}
                >
                  <span className="od-cmdk__item-label">{name}</span>
                  <span className="od-cmdk__item-hint">{hit.hint || 'Favorited here'}</span>
                </Command.Item>
              )
            })}
          </Command.Group>
        ) : null}

        {showLibraryGroup && libraryHits.length > 0 ? (
          <Command.Group heading="Search library" className="od-cmdk__group">
            {libraryHits.map((hit) => {
              const uuid = hit.uuid || hit.id
              const name = hit.name || 'Untitled'
              return (
                <Command.Item
                  key={`lib-${uuid}`}
                  value={`library ${name} ${uuid}`}
                  keywords={[name, String(uuid)]}
                  className="od-cmdk__item"
                  onSelect={() => openTitle({ uuid, name })}
                >
                  <span className="od-cmdk__item-label">{name}</span>
                  <span className="od-cmdk__item-hint">Open details</span>
                </Command.Item>
              )
            })}
          </Command.Group>
        ) : null}

        {groups.map(([heading, items]) => (
          <Command.Group key={heading} heading={heading} className="od-cmdk__group">
            {items.map((cmd: any) => (
              <Command.Item
                key={cmd.id}
                value={`${cmd.label} ${cmd.id}`}
                keywords={[cmd.label, cmd.id, cmd.to, cmd.href].filter(Boolean)}
                className="od-cmdk__item"
                onSelect={() => {
                  void runCommand(cmd)
                }}
              >
                <span className="od-cmdk__item-label">{cmd.label}</span>
                {cmd.to || cmd.href ? (
                  <span className="od-cmdk__item-hint">{cmd.to || cmd.href}</span>
                ) : null}
              </Command.Item>
            ))}
          </Command.Group>
        ))}
      </Command.List>
    </Command.Dialog>
  )
}
