import { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, PageStatus, confirmAction, openPreferencesModal } from '@oneirodex/ui'
import { deleteJson, getJson, postForm, postJson, putJson } from '../api/adminApi'
import { Page } from '../components/Page'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'
import './ThemesPage.css'

type Theme = {
  folder: string
  name: string
  author?: string
  release_date?: string
  description?: string
}
type Motif = { id: string; name: string; family?: string; description?: string }
type ThemeInventory = {
  themes: Theme[]
  default_theme: Record<string, unknown> | null
  active_theme: string
}
type LoadingConfig = {
  loading_icon_mode: 'rotate' | 'lock'
  loading_icon_id: string | null
  catalogue: Motif[]
}

export function ThemesPage() {
  const [inventory, setInventory] = useState<ThemeInventory | null>(null)
  const [loadingConfig, setLoadingConfig] = useState<LoadingConfig | null>(null)
  const [pageLoading, setPageLoading] = useState(true)
  const [pageError, setPageError] = useState('')
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [mode, setMode] = useState<'rotate' | 'lock'>('rotate')
  const [iconId, setIconId] = useState('')
  const [saved, setSaved] = useState(false)

  const load = useCallback(async () => {
    setPageLoading(true)
    setPageError('')
    try {
      const [themes, icons] = await Promise.all([
        getJson('/api/admin/themes'),
        getJson('/api/admin/themes/loading-icons'),
      ])
      if (!Array.isArray(themes?.themes) || !Array.isArray(icons?.catalogue))
        throw new Error('Theme settings response was incomplete.')
      setInventory(themes as ThemeInventory)
      setLoadingConfig(icons as LoadingConfig)
      setMode(icons.loading_icon_mode === 'lock' ? 'lock' : 'rotate')
      setIconId(icons.loading_icon_id || icons.catalogue[0]?.id || '')
    } catch (error) {
      setPageError(errorText(error))
    } finally {
      setPageLoading(false)
    }
  }, [reload])
  useEffect(() => {
    void load()
  }, [load])

  const grouped = useMemo(() => {
    const groups = new Map<string, Motif[]>()
    for (const motif of loadingConfig?.catalogue || []) {
      const family = motif.family || 'Other'
      groups.set(family, [...(groups.get(family) || []), motif])
    }
    return [...groups.entries()]
  }, [loadingConfig])

  async function uploadTheme(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!file) return
    const formElement = event.currentTarget
    setBusy(true)
    try {
      const form = new FormData()
      form.append('theme_zip', file)
      await postForm('/api/admin/themes', form)
      setFile(null)
      formElement.reset()
      showToast('Theme pack uploaded.', 'success')
      setReload((n) => n + 1)
    } catch (error) {
      showToast(errorText(error), 'error')
    } finally {
      setBusy(false)
    }
  }

  async function deleteTheme(theme: Theme) {
    if (
      !(await confirmAction({
        title: `Delete ${theme.name}?`,
        body: 'This removes the uploaded theme pack. Members using it will return to the default theme.',
        confirmLabel: 'Delete theme',
        tone: 'danger',
      }))
    )
      return
    setBusy(true)
    try {
      await deleteJson(`/api/admin/themes/${encodeURIComponent(theme.folder)}`)
      showToast(`${theme.name} deleted.`, 'success')
      setReload((n) => n + 1)
    } catch (error) {
      showToast(errorText(error), 'error')
    } finally {
      setBusy(false)
    }
  }

  async function saveLoadingIcon() {
    setBusy(true)
    setSaved(false)
    try {
      await putJson('/api/admin/loading-icon/config', {
        loading_icon_mode: mode,
        loading_icon_id: mode === 'lock' ? iconId : null,
      })
      setSaved(true)
      showToast('Loading icon settings saved.', 'success')
      setReload((n) => n + 1)
    } catch (error) {
      showToast(errorText(error), 'error')
    } finally {
      setBusy(false)
    }
  }

  async function resetThemes() {
    if (
      !(await confirmAction({
        title: 'Reset default themes?',
        body: 'This replaces the default theme files and preset themes with the bundled versions. Uploaded theme packs are retained.',
        confirmLabel: 'Reset default themes',
        tone: 'danger',
      }))
    )
      return
    setBusy(true)
    try {
      await postJson('/admin/themes/reset', {})
      showToast('Default themes reset. Reload to see them.', 'success')
    } catch (error) {
      showToast(errorText(error), 'error')
    } finally {
      setBusy(false)
    }
  }

  const activeTheme = inventory?.themes.find((theme) => theme.folder === inventory.active_theme)
  const customThemes = (inventory?.themes || []).filter(
    (theme) => theme.folder.toLowerCase() !== 'default',
  )
  const selectedMotif = loadingConfig?.catalogue.find((motif) => motif.id === iconId)

  return (
    <Page
      title="Themes"
      lede="Manage installed theme packs and choose the loading motif used across Oneirodex."
    >
      <PageStatus
        loading={pageLoading && !inventory}
        loadingMessage="Loading themes…"
        error={pageError || null}
      />
      {pageError ? (
        <Button disabled={pageLoading} onClick={() => setReload((n) => n + 1)}>
          Retry loading themes
        </Button>
      ) : null}
      {inventory ? (
        <>
          <section className="od-admin-panel od-themes-active" aria-label="Current theme">
            <div>
              <h2>Current theme</h2>
              <p>
                {activeTheme?.name || inventory.active_theme || 'Default'} is active for your
                account.
              </p>
            </div>
            <Button variant="secondary" onClick={() => void openPreferencesModal()}>
              Choose your theme in Preferences
            </Button>
          </section>

          <section
            className="od-admin-panel od-themes-loading"
            aria-labelledby="loading-motif-title"
          >
            <div>
              <h2 id="loading-motif-title">Loading motif</h2>
              <p>Choose a rotating catalogue or lock loading indicators to one motif.</p>
            </div>
            <fieldset className="od-themes-mode">
              <legend>Loading behavior</legend>
              <label>
                <input
                  type="radio"
                  name="loading-mode"
                  value="rotate"
                  checked={mode === 'rotate'}
                  onChange={() => {
                    setMode('rotate')
                    setSaved(false)
                  }}
                />{' '}
                Rotate through motifs
              </label>
              <label>
                <input
                  type="radio"
                  name="loading-mode"
                  value="lock"
                  checked={mode === 'lock'}
                  onChange={() => {
                    setMode('lock')
                    setSaved(false)
                  }}
                />{' '}
                Use one motif
              </label>
            </fieldset>
            {mode === 'lock' ? (
              <div className="od-field">
                <label htmlFor="loading-motif">Motif</label>
                <select
                  id="loading-motif"
                  value={iconId}
                  onChange={(event) => {
                    setIconId(event.target.value)
                    setSaved(false)
                  }}
                >
                  {grouped.map(([family, options]) => (
                    <optgroup key={family} label={family}>
                      {options.map((option) => (
                        <option key={option.id} value={option.id}>
                          {option.name}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
                {selectedMotif ? <p>{selectedMotif.description}</p> : null}
              </div>
            ) : null}
            <div className="od-admin-actions-row">
              <Button disabled={busy || (mode === 'lock' && !iconId)} onClick={saveLoadingIcon}>
                Save loading motif
              </Button>
              {saved ? (
                <PageStatus announcement="status" inline>
                  Saved
                </PageStatus>
              ) : null}
            </div>
          </section>

          <section className="od-admin-panel od-themes-upload" aria-labelledby="upload-theme-title">
            <div>
              <h2 id="upload-theme-title">Upload a theme pack</h2>
              <p>
                Upload a ZIP containing theme.json and a CSS folder. Maximum archive size: 25 MB.
              </p>
            </div>
            <form onSubmit={uploadTheme}>
              <div className="od-field">
                <label htmlFor="theme-zip">Theme ZIP</label>
                <input
                  id="theme-zip"
                  type="file"
                  accept=".zip,application/zip"
                  onChange={(event) => setFile(event.target.files?.[0] || null)}
                />
              </div>
              <Button disabled={busy || !file} type="submit">
                Upload theme
              </Button>
            </form>
          </section>

          <section className="od-admin-panel" aria-labelledby="installed-themes-title">
            <h2 id="installed-themes-title">Installed themes</h2>
            {inventory.themes.length ? (
              <ul className="od-themes-list">
                {inventory.themes.map((theme) => (
                  <li key={theme.folder}>
                    <div>
                      <h3>
                        {theme.name}{' '}
                        {theme.folder === inventory.active_theme ? (
                          <span className="od-badge">Active</span>
                        ) : null}
                      </h3>
                      <p>{theme.description || 'No description available'}</p>
                      <small>
                        By {theme.author || 'Unknown'} ·{' '}
                        {theme.release_date || 'Unknown release date'}
                      </small>
                    </div>
                    {theme.folder.toLowerCase() !== 'default' ? (
                      <Button
                        variant="danger"
                        disabled={busy}
                        onClick={() => void deleteTheme(theme)}
                      >
                        Delete
                      </Button>
                    ) : (
                      <span className="od-themes-default">Built in</span>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p>No installed themes were found.</p>
            )}
          </section>

          <section className="od-admin-panel od-themes-maintenance">
            <div>
              <h2>Default theme files</h2>
              <p>
                After updating the bundled theme files, reset them to sync the installed defaults.
                Uploaded theme packs are retained.
              </p>
            </div>
            <div className="od-admin-actions-row">
              <Button variant="danger" disabled={busy} onClick={resetThemes}>
                Reset Default Themes
              </Button>
              <a className="od-btn" href="/admin/themes/readme">
                Theme authoring guide
              </a>
            </div>
          </section>
        </>
      ) : null}
    </Page>
  )
}
