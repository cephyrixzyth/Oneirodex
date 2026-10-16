import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Modal } from './Modal.js'
import { getPreferences, putPreferences, type PreferencesPayload } from './preferencesApi.js'
import { csrfHeaders } from './csrf.js'
import { errorFromResponse } from './envelopeError.js'
import { RailIcon } from './railIcons.js'
import './PreferencesModal.css'

interface Props {
  open: boolean
  onClose: () => void
}
const LABELS: Record<string, string> = {
  items_per_page: 'Max items per page',
  default_sort: 'Default sort',
  default_sort_order: 'Default sort order',
  font: 'Font',
  preferred_game_locale: 'Preferred game language',
  browser_player_engine: 'Play in browser with',
}

function SelectField({
  name,
  value,
  choices,
  onChange,
}: {
  name: string
  value: string
  choices: Array<{ value: string; label: string }>
  onChange: (value: string) => void
}) {
  return (
    <label className="od-preferences__field">
      <span>{LABELS[name]}</span>
      <select
        className="od-preferences__select"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {choices.map((choice) => (
          <option key={choice.value} value={choice.value}>
            {choice.label}
          </option>
        ))}
      </select>
    </label>
  )
}

function PrefsSection({
  id,
  title,
  description,
  collapsed,
  onToggle,
  children,
}: {
  id: string
  title: string
  description: string
  collapsed: boolean
  onToggle: (id: string, open: boolean) => void
  children: ReactNode
}) {
  return (
    <details
      className="od-preferences__section"
      data-prefs-section={id}
      open={!collapsed}
      onToggle={(event) => onToggle(id, event.currentTarget.open)}
    >
      <summary>
        <h3>{title}</h3>
      </summary>
      <p>{description}</p>
      {children}
    </details>
  )
}

export function PreferencesModal({ open, onClose }: Props): ReactNode {
  const [data, setData] = useState<PreferencesPayload | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [installPrompt, setInstallPrompt] = useState<BeforeInstallPromptEvent | null>(null)
  const [installDismissed, setInstallDismissed] = useState(false)
  const [installed, setInstalled] = useState(false)
  const [collapsedSections, setCollapsedSections] = useState<string[]>(() => {
    try {
      const stored = JSON.parse(window.localStorage.getItem('od.prefs.collapsedSections') || '[]')
      return Array.isArray(stored)
        ? stored.filter((value): value is string => typeof value === 'string')
        : []
    } catch {
      return []
    }
  })
  const previewOriginal = useRef<{
    accent: string
    legacyAccent: string
    era: string | null
    iconPack: string | null
    iconHref: string | null
  } | null>(null)

  function rememberPreview() {
    if (previewOriginal.current) return
    const root = document.documentElement
    const link = document.getElementById('od-icon-pack-css') as HTMLLinkElement | null
    previewOriginal.current = {
      accent: root.style.getPropertyValue('--od-accent'),
      legacyAccent: root.style.getPropertyValue('--btn-primary'),
      era: root.getAttribute('data-era'),
      iconPack: root.getAttribute('data-icon-pack'),
      iconHref: link?.getAttribute('href') || null,
    }
  }

  function previewIconPack(pack: string) {
    rememberPreview()
    const root = document.documentElement
    root.setAttribute('data-icon-pack', pack)
    const link = document.getElementById('od-icon-pack-css') as HTMLLinkElement | null
    if (link?.href)
      link.href = link.href.replace(
        /library\/icon-themes\/[^/]+\/pack\.css/,
        `library/icon-themes/${encodeURIComponent(pack)}/pack.css`,
      )
  }

  function previewTheme(theme: { slug: string; era: string; icon_pack?: string }) {
    rememberPreview()
    const root = document.documentElement
    const card = document.querySelector(`[data-theme-preview="${CSS.escape(theme.slug)}"]`)
    const chip = card?.querySelector('.theme-swatch-chip')
    const accent = chip ? getComputedStyle(chip).backgroundColor : ''
    if (accent && accent !== 'transparent' && accent !== 'rgba(0, 0, 0, 0)') {
      root.style.setProperty('--od-accent', accent)
      root.style.setProperty('--btn-primary', accent)
    }
    if (theme.era) root.setAttribute('data-era', theme.era)
    if (theme.icon_pack) previewIconPack(theme.icon_pack)
  }

  function clearPreview() {
    const original = previewOriginal.current
    if (!original) return
    const root = document.documentElement
    for (const [key, value] of [
      ['--od-accent', original.accent],
      ['--btn-primary', original.legacyAccent],
    ] as const) {
      if (value) root.style.setProperty(key, value)
      else root.style.removeProperty(key)
    }
    if (original.era) root.setAttribute('data-era', original.era)
    else root.removeAttribute('data-era')
    if (original.iconPack) root.setAttribute('data-icon-pack', original.iconPack)
    else root.removeAttribute('data-icon-pack')
    const link = document.getElementById('od-icon-pack-css')
    if (link) {
      if (original.iconHref) link.setAttribute('href', original.iconHref)
      else link.removeAttribute('href')
    }
    previewOriginal.current = null
  }

  useEffect(() => {
    const prompt = (event: Event) => {
      event.preventDefault()
      setInstallPrompt(event as BeforeInstallPromptEvent)
    }
    const complete = () => {
      setInstallPrompt(null)
      setInstalled(true)
    }
    setInstalled(
      Boolean(
        window.matchMedia?.('(display-mode: standalone)').matches ||
        (navigator as Navigator & { standalone?: boolean }).standalone,
      ),
    )
    try {
      setInstallDismissed(window.localStorage.getItem('od-install-dismissed') === '1')
    } catch {
      setInstallDismissed(false)
    }
    window.addEventListener('beforeinstallprompt', prompt)
    window.addEventListener('appinstalled', complete)
    return () => {
      window.removeEventListener('beforeinstallprompt', prompt)
      window.removeEventListener('appinstalled', complete)
    }
  }, [])

  useEffect(() => {
    if (!open) clearPreview()
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    const controller = new AbortController()
    setError('')
    getPreferences(controller.signal)
      .then((result) => {
        setData(result)
        setValues(result.preferences)
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(reason instanceof Error ? reason.message : 'Preferences could not be loaded.')
      })
    return () => controller.abort()
  }, [open])

  const update = (key: string, value: string) => {
    setValues((before) => ({ ...before, [key]: value }))
    setSaved(false)
    if (key === 'icon_pack') previewIconPack(value)
  }
  const toggleSection = (id: string, open: boolean) => {
    setCollapsedSections((before) => {
      const next = open ? before.filter((value) => value !== id) : [...new Set([...before, id])]
      try {
        window.localStorage.setItem('od.prefs.collapsedSections', JSON.stringify(next))
      } catch {
        /* optional local preference */
      }
      return next
    })
  }
  async function save() {
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      const result = await putPreferences(values)
      setValues(result.preferences)
      setSaved(true)
      window.setTimeout(() => window.location.reload(), 650)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Preferences could not be saved.')
    } finally {
      setSaving(false)
    }
  }

  async function resetThemes() {
    if (
      !window.confirm(
        'Replace the old shipped presets with the current designs? Uploaded themes are kept.',
      )
    )
      return
    setError('')
    try {
      const response = await fetch('/admin/themes/reset', {
        method: 'POST',
        credentials: 'same-origin',
        headers: csrfHeaders({ 'Content-Type': 'application/json' }),
        body: '{}',
      })
      if (!response.ok) throw await errorFromResponse(response, 'theme reset failed')
      window.location.reload()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Themes could not be reset.')
    }
  }

  async function installApp() {
    if (!installPrompt) return
    await installPrompt.prompt()
    const result = await installPrompt.userChoice
    setInstallPrompt(null)
    if (result.outcome === 'accepted') setInstalled(true)
  }

  return (
    <Modal
      open={open}
      onClose={() => {
        clearPreview()
        onClose()
      }}
      label="Preferences"
      className="od-preferences__scrim"
      panelClassName="od-preferences"
      lockScroll
    >
      <header className="od-preferences__header">
        <div>
          <p className="od-preferences__eyebrow">Your library</p>
          <h2>Preferences</h2>
        </div>
        <button
          type="button"
          className="od-preferences__close"
          aria-label="Close preferences"
          onClick={onClose}
        >
          ×
        </button>
      </header>
      <div className="od-preferences__body">
        {error && (
          <p className="od-preferences__message" role="alert">
            {error}
          </p>
        )}
        {!data && !error && <p role="status">Loading preferences…</p>}
        {data && (
          <>
            <PrefsSection
              id="prefs-library-heading"
              title="Library"
              description="Choose your default page size and sort."
              collapsed={collapsedSections.includes('prefs-library-heading')}
              onToggle={toggleSection}
            >
              <div className="od-preferences__grid">
                <SelectField
                  name="items_per_page"
                  value={values.items_per_page}
                  choices={data.choices.items_per_page}
                  onChange={(v) => update('items_per_page', v)}
                />
                <SelectField
                  name="default_sort"
                  value={values.default_sort}
                  choices={data.choices.default_sort}
                  onChange={(v) => update('default_sort', v)}
                />
                <SelectField
                  name="default_sort_order"
                  value={values.default_sort_order}
                  choices={data.choices.default_sort_order}
                  onChange={(v) => update('default_sort_order', v)}
                />
              </div>
            </PrefsSection>
            <PrefsSection
              id="prefs-look-heading"
              title="Look & density"
              description="Each design pairs a dark room, distinct controls, and its own icon language. Theme and icons are independent; tile size is continuous."
              collapsed={collapsedSections.includes('prefs-look-heading')}
              onToggle={toggleSection}
            >
              <span className="od-preferences__label">Theme</span>
              {data.choices.themes.map((group) => (
                <div className="od-preferences__theme-group" key={group.id}>
                  <h4>{group.label}</h4>
                  {group.hint && <p>{group.hint}</p>}
                  <div
                    className="od-preferences__themes"
                    id={group.id === data.choices.themes[0]?.id ? 'themeSwatchGrid' : undefined}
                  >
                    {group.items.map((theme) => (
                      <button
                        type="button"
                        key={theme.slug}
                        data-theme-preview={theme.slug}
                        className={`od-preferences__theme theme-swatch theme-card${values.theme === theme.slug ? ' is-selected' : ''}`}
                        aria-pressed={values.theme === theme.slug}
                        onClick={() => {
                          update('theme', theme.slug)
                          if (theme.icon_pack) update('icon_pack', theme.icon_pack)
                          previewTheme(theme)
                        }}
                      >
                        <span
                          className="theme-card-preview"
                          data-era={theme.era}
                          aria-hidden="true"
                        >
                          <span className="od-era-wall" />
                          <span className="od-era-window" />
                          <span className="od-era-posters" />
                          <span className="od-era-furnish" />
                          <span className="od-era-stand" />
                          <span className="od-era-floor" />
                          <span className="od-era-lamp" />
                          <span className={`theme-swatch-chip theme-swatch-${theme.slug}`} />
                        </span>
                        <strong>{theme.name}</strong>
                        {theme.description && <small>{theme.description}</small>}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
              <span className="od-preferences__label">Icon pack</span>
              <div className="od-preferences__icon-packs" id="iconPackPreview">
                {data.choices.icon_packs.map((pack) => (
                  <button
                    type="button"
                    key={pack.id}
                    className={`od-preferences__icon-pack icon-pack-chip${values.icon_pack === pack.id ? ' is-selected' : ''}`}
                    data-icon-pack={pack.id}
                    aria-pressed={values.icon_pack === pack.id}
                    onClick={() => update('icon_pack', pack.id)}
                  >
                    <span className="icon-pack-chip-icons" data-preview-pack={pack.id}>
                      <RailIcon name="library" size={16} />
                      <RailIcon name="discover" size={16} />
                      <RailIcon name="systems" size={16} />
                      <RailIcon name="download" size={16} />
                      <RailIcon name="favorites" size={16} />
                    </span>
                    <span className="icon-pack-chip-label">{pack.name}</span>
                  </button>
                ))}
              </div>
              <div className="od-preferences__grid">
                <SelectField
                  name="font"
                  value={values.font}
                  choices={data.choices.fonts}
                  onChange={(v) => update('font', v)}
                />
                <label className="od-preferences__field">
                  <span>Tile size: {values.tile_size}%</span>
                  <input
                    className="od-preferences__range"
                    type="range"
                    min="0"
                    max="100"
                    step="1"
                    value={values.tile_size}
                    onChange={(event) => update('tile_size', event.target.value)}
                  />
                </label>
              </div>
              <label className="od-preferences__check">
                <input
                  type="checkbox"
                  checked={values.show_tile_titles !== 'false'}
                  onChange={(event) =>
                    update('show_tile_titles', event.target.checked ? 'true' : 'false')
                  }
                />
                Show titles under tiles
              </label>
              {data.is_admin && (
                <div className="od-preferences__hint">
                  <p>
                    After a deploy that changes theme CSS, reset the library volume copies so Look
                    matches the image.
                  </p>
                  <button
                    type="button"
                    className="od-preferences__secondary"
                    onClick={() => void resetThemes()}
                  >
                    Reset default themes
                  </button>
                </div>
              )}
            </PrefsSection>
            {data.member_engine_choice && (
              <PrefsSection
                id="prefs-play-heading"
                title="Play in browser"
                description="Choose which emulator shell opens when you press Play."
                collapsed={collapsedSections.includes('prefs-play-heading')}
                onToggle={toggleSection}
              >
                <SelectField
                  name="browser_player_engine"
                  value={values.browser_player_engine}
                  choices={data.choices.browser_player_engines}
                  onChange={(v) => update('browser_player_engine', v)}
                />
              </PrefsSection>
            )}
            <PrefsSection
              id="prefs-lang-heading"
              title="Game language"
              description="Content language preference, separate from interface language."
              collapsed={collapsedSections.includes('prefs-lang-heading')}
              onToggle={toggleSection}
            >
              <SelectField
                name="preferred_game_locale"
                value={values.preferred_game_locale}
                choices={data.choices.game_locales}
                onChange={(v) => update('preferred_game_locale', v)}
              />
            </PrefsSection>
            {window.isSecureContext && !installed && !installDismissed && (
              <PrefsSection
                id="prefs-install-heading"
                title="Install this library"
                description="Run the library in its own window. Games and covers stay on the server."
                collapsed={collapsedSections.includes('prefs-install-heading')}
                onToggle={toggleSection}
              >
                {installPrompt ? (
                  <button
                    type="button"
                    className="od-preferences__secondary"
                    onClick={() => void installApp()}
                  >
                    Install
                  </button>
                ) : (
                  <p className="od-preferences__hint">
                    Use your browser’s install control — Share → Add to Home Screen on iPhone and
                    iPad, or the install icon in the address bar.
                  </p>
                )}
                <button
                  type="button"
                  className="od-preferences__text-button"
                  onClick={() => {
                    setInstallDismissed(true)
                    try {
                      window.localStorage.setItem('od-install-dismissed', '1')
                    } catch {
                      /* storage is optional */
                    }
                  }}
                >
                  Not now
                </button>
              </PrefsSection>
            )}
          </>
        )}
      </div>
      <footer className="od-preferences__footer">
        <span role="status">{saved ? 'Preferences saved.' : ''}</span>
        <button type="button" className="od-preferences__secondary" onClick={onClose}>
          Cancel
        </button>
        <button
          type="button"
          className="od-preferences__primary"
          disabled={!data || saving}
          onClick={() => void save()}
        >
          {saving ? 'Saving…' : 'Save changes'}
        </button>
      </footer>
    </Modal>
  )
}

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed'; platform?: string }>
}
