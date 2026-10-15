import { useEffect, useState, type FormEvent } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { Page } from '../components/Page'
import { getJson, putJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'

const API = '/api/admin/attract-mode/settings'
type Option = { id: number; name: string }
interface Config {
  enabled: boolean
  idle_timeout: number | string
  filters: {
    library_uuid: string | null
    genres: number[]
    themes: number[]
    date_from: number | string | null
    date_to: number | string | null
  }
  autoplay: { enabled: boolean; skipFirst: number | string; skipAfter: number | string }
}
const EMPTY: Config = {
  enabled: false,
  idle_timeout: 60,
  filters: { library_uuid: null, genres: [], themes: [], date_from: null, date_to: null },
  autoplay: { enabled: true, skipFirst: 0, skipAfter: 0 },
}
const BOUNDS = {
  idle_timeout: { min: 10, max: 300 },
  skipFirst: { min: 0, max: 300 },
  skipAfter: { min: 0, max: 600 },
  year: { min: 1, max: 9999 },
}

export function AttractModePage() {
  const [form, setForm] = useState<Config>(EMPTY)
  const [options, setOptions] = useState<{
    libraries: { uuid: string; name: string }[]
    genres: Option[]
    themes: Option[]
    date_range?: { min_year: number | null; max_year: number | null }
  }>({ libraries: [], genres: [], themes: [] })
  const [bounds, setBounds] = useState(BOUNDS)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [reload, setReload] = useState(0)
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadFailed(false)
    setError('')
    getJson(API)
      .then((data) => {
        if (cancelled) return
        if (
          !data.settings?.filters ||
          !data.settings?.autoplay ||
          !Array.isArray(data.filter_options?.libraries) ||
          !Array.isArray(data.filter_options?.genres) ||
          !Array.isArray(data.filter_options?.themes)
        )
          throw new Error('Attract mode settings returned an invalid response.')
        setForm(data.settings)
        setOptions(data.filter_options)
        setBounds(data.bounds || BOUNDS)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorText(err))
          setLoadFailed(true)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [reload])
  function edit(next: Config) {
    if (!busy) {
      setForm(next)
      setMessage('')
    }
  }
  function filter(key: keyof Config['filters'], value: any) {
    edit({ ...form, filters: { ...form.filters, [key]: value } })
  }
  function autoplay(key: keyof Config['autoplay'], value: any) {
    edit({ ...form, autoplay: { ...form.autoplay, [key]: value } })
  }
  async function save(event: FormEvent) {
    event.preventDefault()
    if (loading || loadFailed || busy) return
    setBusy(true)
    setError('')
    setMessage('')
    const year = (value: number | string | null) =>
      value === null || value === '' ? null : Number(value)
    try {
      const data = await putJson(API, {
        ...form,
        idle_timeout: Number(form.idle_timeout),
        filters: {
          ...form.filters,
          date_from: year(form.filters.date_from),
          date_to: year(form.filters.date_to),
        },
        autoplay: {
          ...form.autoplay,
          skipFirst: Number(form.autoplay.skipFirst),
          skipAfter: Number(form.autoplay.skipAfter),
        },
      })
      if (!data.settings?.filters || !data.settings?.autoplay)
        throw new Error('Attract mode settings returned an invalid response.')
      setForm(data.settings)
      setMessage('Attract mode settings saved.')
      showToast('Attract mode settings saved.', 'success')
    } catch (err) {
      const text = errorText(err) || 'Could not save attract mode settings.'
      setError(text)
      showToast(text, 'error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Page title="Attract mode" lede="Configure automatic trailer playback when the system is idle.">
      <PageStatus
        loading={loading}
        loadingMessage="Loading attract mode settings…"
        error={error || null}
      />
      {loadFailed ? (
        <Button onClick={() => setReload((value) => value + 1)}>Retry loading settings</Button>
      ) : null}
      {!loading ? (
        <form className="od-admin-panel" onSubmit={save}>
          <fieldset className="od-admin-fieldset" disabled={busy || loadFailed}>
            <legend>General settings</legend>
            <label className="od-admin-field">
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={(e) => edit({ ...form, enabled: e.target.checked })}
              />{' '}
              Enable attract mode
            </label>
            <label className="od-admin-field">
              Idle timeout (seconds)
              <input
                className="od-admin-input"
                type="number"
                required
                step={1}
                {...bounds.idle_timeout}
                value={form.idle_timeout}
                onChange={(e) => edit({ ...form, idle_timeout: e.target.value })}
              />
            </label>
          </fieldset>
          <fieldset className="od-admin-fieldset" disabled={busy || loadFailed}>
            <legend>Trailer filters</legend>
            <label className="od-admin-field">
              Library
              <select
                aria-label="Library"
                className="od-admin-input"
                value={form.filters.library_uuid || ''}
                onChange={(e) => filter('library_uuid', e.target.value || null)}
              >
                <option value="">All libraries</option>
                {form.filters.library_uuid &&
                !options.libraries.some((row) => row.uuid === form.filters.library_uuid) ? (
                  <option value={form.filters.library_uuid}>Saved library (unavailable)</option>
                ) : null}
                {options.libraries.map((row) => (
                  <option key={row.uuid} value={row.uuid}>
                    {row.name}
                  </option>
                ))}
              </select>
            </label>
            {(['genres', 'themes'] as const).map((key) => (
              <label key={key} className="od-admin-field">
                {key === 'genres' ? 'Genres' : 'Themes'}
                <select
                  aria-label={key === 'genres' ? 'Genres' : 'Themes'}
                  className="od-admin-input"
                  multiple
                  size={5}
                  value={form.filters[key].map(String)}
                  onChange={(e) =>
                    filter(
                      key,
                      Array.from(e.target.selectedOptions, (option) => Number(option.value)),
                    )
                  }
                >
                  {options[key].map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.name}
                    </option>
                  ))}
                </select>
                <span className="od-admin-hint">Select multiple options with Ctrl or Command.</span>
              </label>
            ))}
            <label className="od-admin-field">
              From year
              <input
                className="od-admin-input"
                type="number"
                step={1}
                {...bounds.year}
                value={form.filters.date_from ?? ''}
                onChange={(e) => filter('date_from', e.target.value || null)}
              />
            </label>
            <label className="od-admin-field">
              To year
              <input
                className="od-admin-input"
                type="number"
                step={1}
                {...bounds.year}
                value={form.filters.date_to ?? ''}
                onChange={(e) => filter('date_to', e.target.value || null)}
              />
            </label>
            {options.date_range?.min_year && options.date_range?.max_year ? (
              <p className="od-admin-hint">
                Available trailers span {options.date_range.min_year}–{options.date_range.max_year}.
              </p>
            ) : null}
          </fieldset>
          <fieldset className="od-admin-fieldset" disabled={busy || loadFailed}>
            <legend>Autoplay</legend>
            <label className="od-admin-field">
              <input
                type="checkbox"
                checked={form.autoplay.enabled}
                onChange={(e) => autoplay('enabled', e.target.checked)}
              />{' '}
              Enable autoplay
            </label>
            <label className="od-admin-field">
              Skip first (seconds)
              <input
                className="od-admin-input"
                type="number"
                required
                step={1}
                {...bounds.skipFirst}
                value={form.autoplay.skipFirst}
                onChange={(e) => autoplay('skipFirst', e.target.value)}
              />
            </label>
            <label className="od-admin-field">
              Skip after (seconds)
              <input
                className="od-admin-input"
                type="number"
                required
                step={1}
                {...bounds.skipAfter}
                value={form.autoplay.skipAfter}
                onChange={(e) => autoplay('skipAfter', e.target.value)}
              />
            </label>
            <p className="od-admin-hint">Set skip after to 0 to play the full trailer.</p>
          </fieldset>
          <section className="od-admin-panel" aria-label="Configuration preview">
            <h2>Configuration preview</h2>
            <p>
              {form.enabled
                ? `Attract mode activates after ${form.idle_timeout} seconds of inactivity.`
                : 'Attract mode is disabled.'}
            </p>
            <p>
              Members can override the trailer filters and autoplay settings for their own
              experience.
            </p>
          </section>
          <Button type="submit" variant="primary" disabled={busy || loadFailed}>
            {busy ? 'Saving…' : 'Save settings'}
          </Button>
          {message ? (
            <PageStatus announcement="status" className="od-admin-hint">
              {message}
            </PageStatus>
          ) : null}
        </form>
      ) : null}
    </Page>
  )
}
