import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { Button, PageStatus, confirmAction } from '@oneirodex/ui'
import { getJson, postJson, putJson } from '../api/adminApi'
import { Page } from '../components/Page'
import { Candidate, Options, TAXONOMIES } from './manualIdentifyTypes'
import './ManualIdentifyPage.css'

export function ManualIdentifyPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const { gameUuid } = useParams()
  const editing = Boolean(gameUuid)
  const query = useMemo(() => new URLSearchParams(location.search), [location.search])
  const [options, setOptions] = useState<Options | null>(null)
  const [loadError, setLoadError] = useState('')
  const [searchText, setSearchText] = useState(query.get('name') || '')
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [searchBusy, setSearchBusy] = useState(false)
  const [searchSource, setSearchSource] = useState('IGDB')
  const [form, setForm] = useState<Record<string, any>>({
    igdb_id: query.get('igdb_id') || '',
    name: query.get('name') || '',
    full_disk_path: query.get('full_disk_path') || '',
    library_uuid: query.get('library_uuid') || '',
    summary: '',
    storyline: '',
    url: '',
    video_urls: '',
    first_release_date: '',
    aggregated_rating: '',
    category: '',
    status: '',
    developer: '',
    publisher: '',
    item_kind: '',
    provider_urls: {},
    genre_ids: [],
    game_mode_ids: [],
    theme_ids: [],
    platform_ids: [],
    player_perspective_ids: [],
  })
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [scanRunning, setScanRunning] = useState(false)
  const [linkQuery, setLinkQuery] = useState('')
  const [linkHits, setLinkHits] = useState<
    Array<{ uuid: string; name: string; full_disk_path?: string | null }>
  >([])
  const [linkSelected, setLinkSelected] = useState<{
    uuid: string
    name: string
    full_disk_path?: string | null
  } | null>(null)
  const [linkSearching, setLinkSearching] = useState(false)
  const [linkBusy, setLinkBusy] = useState(false)
  const [linkError, setLinkError] = useState('')
  const [linkSearched, setLinkSearched] = useState(false)

  useEffect(() => {
    let live = true
    getJson('/api/admin/manual-identify/options')
      .then((data) => {
        if (!live) return
        if (!Array.isArray(data.libraries) || !data.taxonomies)
          throw new Error('Manual identify options returned an invalid response.')
        setOptions(data as Options)
        setForm((current) => ({
          ...current,
          library_uuid: current.library_uuid || data.libraries[0]?.uuid || '',
        }))
      })
      .catch((error) => {
        if (live)
          setLoadError(error instanceof Error ? error.message : 'Unable to load identify options.')
      })
    return () => {
      live = false
    }
  }, [])

  useEffect(() => {
    if (!gameUuid) return
    let live = true
    getJson(`/api/admin/manual-identify/${encodeURIComponent(gameUuid)}`)
      .then((payload) => {
        if (!live) return
        setForm((current) => ({ ...current, ...payload.game }))
        setSearchText(payload.game?.name || '')
        setLinkQuery(payload.game?.name || '')
        setScanRunning(Boolean(payload.scan_running))
      })
      .catch((error) => {
        if (live)
          setLoadError(
            error instanceof Error ? error.message : 'Unable to load this game for editing.',
          )
      })
    return () => {
      live = false
    }
  }, [gameUuid])

  const setField = (name: string, value: unknown) =>
    setForm((current) => ({ ...current, [name]: value }))

  async function search(event: FormEvent) {
    event.preventDefault()
    const term = searchText.trim()
    if (!term || searchBusy) return
    setSearchBusy(true)
    setSearchSource('IGDB')
    setSaveError('')
    try {
      const params = new URLSearchParams({ name: term })
      const data = await getJson(`/api/search_igdb_by_name?${params}`)
      setCandidates(Array.isArray(data.results) ? data.results : [])
      if (!Array.isArray(data.results) || !data.results.length)
        setSaveError('No IGDB matches found. You can still enter the metadata manually.')
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : 'IGDB search failed.')
    } finally {
      setSearchBusy(false)
    }
  }

  async function searchProvider(source: string) {
    const term = String(form.name || searchText).trim()
    if (!term || searchBusy) return
    setSearchBusy(true)
    setSearchSource(source.toUpperCase())
    setSaveError('')
    try {
      const params = new URLSearchParams({ name: term, source })
      const data = await getJson(`/api/search_metadata?${params}`)
      setCandidates(Array.isArray(data.results) ? data.results : [])
      if (!Array.isArray(data.results) || !data.results.length)
        setSaveError(data.note || `No ${source.toUpperCase()} matches found.`)
    } catch (error) {
      setSaveError(
        error instanceof Error ? error.message : `${source.toUpperCase()} search failed.`,
      )
    } finally {
      setSearchBusy(false)
    }
  }

  async function chooseProvider(row: Candidate) {
    try {
      const data = await getJson('/api/get_next_custom_igdb_id')
      const provider =
        searchSource.toLowerCase() === 'epic' ? 'epicgames' : searchSource.toLowerCase()
      setForm((current) => ({
        ...current,
        igdb_id: data.next_id,
        name: row.name || current.name,
        summary: row.summary || current.summary,
        url: row.url || current.url,
        provider_urls: { ...current.provider_urls, [provider]: row.url || '' },
      }))
      setCandidates([])
    } catch (error) {
      setSaveError(
        error instanceof Error ? error.message : 'Could not allocate a custom catalog ID.',
      )
    }
  }

  function choose(row: Candidate) {
    const resolveIds = (key: string) =>
      (Array.isArray(row[key]) ? row[key] : [])
        .map((value: unknown) => {
          const name =
            value && typeof value === 'object' ? (value as { name?: unknown }).name : value
          return options?.taxonomies[key]?.find(
            (option) => option.name.toLowerCase() === String(name).toLowerCase(),
          )?.id
        })
        .filter((id: number | undefined): id is number => id !== undefined)
    const timestamp = row.first_release_date
      ? new Date(row.first_release_date * 1000).toISOString().slice(0, 10)
      : ''
    setForm((current) => ({
      ...current,
      igdb_id: row.id,
      name: row.name || '',
      summary: row.summary || '',
      storyline: row.storyline || '',
      url: row.url || '',
      first_release_date: timestamp,
      video_urls: Array.isArray(row.videos)
        ? row.videos
            .map(
              (video: Record<string, unknown>) =>
                `https://www.youtube.com/watch?v=${String(video.video_id ?? '')}`,
            )
            .join(', ')
        : '',
      aggregated_rating: row.aggregated_rating ?? '',
      genres: undefined,
      genre_ids: resolveIds('genres'),
      game_mode_ids: resolveIds('game_modes'),
      theme_ids: resolveIds('themes'),
      platform_ids: resolveIds('platforms'),
      player_perspective_ids: resolveIds('player_perspectives'),
    }))
    setCandidates([])
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (saving || !options || loadError) return
    setSaving(true)
    setSaveError('')
    setFieldErrors({})
    try {
      const body = {
        ...form,
        igdb_id: Number(form.igdb_id),
        genre_ids: form.genre_ids,
        game_mode_ids: form.game_mode_ids,
        theme_ids: form.theme_ids,
        platform_ids: form.platform_ids,
        player_perspective_ids: form.player_perspective_ids,
        first_release_date: form.first_release_date || null,
        aggregated_rating: form.aggregated_rating === '' ? null : Number(form.aggregated_rating),
      }
      const submitUrl = editing
        ? `/api/admin/manual-identify/${encodeURIComponent(gameUuid!)}`
        : fromUnmatched
          ? '/api/admin/manual-identify?from_unmatched=true'
          : '/api/admin/manual-identify'
      const payload = editing ? await putJson(submitUrl, body) : await postJson(submitUrl, body)
      navigate(payload.redirect_url || '/libraries')
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : 'Unable to save this game.')
      const detail = (error as { data?: { detail?: unknown } })?.data?.detail
      if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
        setFieldErrors(
          Object.fromEntries(
            Object.entries(detail).map(([key, value]) => [
              key,
              Array.isArray(value) ? value.join(', ') : String(value),
            ]),
          ),
        )
      }
    } finally {
      setSaving(false)
    }
  }

  const fromUnmatched = query.get('from_unmatched') === 'true'
  async function loadIgdbId() {
    const id = Number(form.igdb_id)
    if (!Number.isInteger(id) || id < 1 || searchBusy) return
    setSearchBusy(true)
    setSearchSource('IGDB')
    try {
      const row = await getJson(`/api/search_igdb_by_id?igdb_id=${id}`)
      choose(row as Candidate)
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : 'Unable to load this IGDB entry.')
    } finally {
      setSearchBusy(false)
    }
  }
  async function addNonCatalogGame() {
    try {
      const data = await getJson('/api/get_next_custom_igdb_id')
      setField('igdb_id', data.next_id)
      setField('item_kind', 'game')
    } catch (error) {
      setSaveError(
        error instanceof Error ? error.message : 'Could not allocate a custom catalog ID.',
      )
    }
  }
  async function searchExistingGames(event: FormEvent) {
    event.preventDefault()
    const term = linkQuery.trim()
    if (term.length < 2 || linkSearching || linkBusy) return
    setLinkSearching(true)
    setLinkError('')
    setLinkHits([])
    setLinkSelected(null)
    setLinkSearched(false)
    try {
      const result = await getJson(`/api/admin/games_search?q=${encodeURIComponent(term)}`)
      if (!Array.isArray(result))
        throw new Error('Existing game search returned an invalid response.')
      setLinkHits(result as Array<{ uuid: string; name: string; full_disk_path?: string | null }>)
      setLinkSearched(true)
    } catch (error) {
      setLinkError(error instanceof Error ? error.message : 'Unable to search existing games.')
    } finally {
      setLinkSearching(false)
    }
  }
  async function linkExistingGame() {
    if (!form.full_disk_path || !form.library_uuid || !linkSelected || linkBusy) return
    const confirmed = await confirmAction({
      title: 'Link this folder to an existing game?',
      body: [
        `Set ${linkSelected.name} to use this folder path?`,
        String(form.full_disk_path),
        'This updates the selected game path and removes any matching unmatched-folder row.',
      ],
      confirmLabel: 'Link folder',
      tone: 'neutral',
    })
    if (!confirmed) return
    setLinkBusy(true)
    setLinkError('')
    try {
      await postJson('/api/library_tools/link_existing_game', {
        game_uuid: linkSelected.uuid,
        full_disk_path: form.full_disk_path,
        library_uuid: form.library_uuid,
        from_unmatched: fromUnmatched,
      })
      navigate(fromUnmatched ? '/admin/scan_management?active_tab=unmatched' : '/libraries')
    } catch (error) {
      setLinkError(error instanceof Error ? error.message : 'Unable to link this folder.')
    } finally {
      setLinkBusy(false)
    }
  }
  return (
    <Page
      title={
        editing ? 'Edit game entry' : fromUnmatched ? 'Identify unmatched folder' : 'Identify game'
      }
      lede={
        editing
          ? 'Update metadata for an existing library title.'
          : 'Search metadata, confirm the game details, then add it to the selected library.'
      }
      className="od-manual-identify"
    >
      <div className="od-admin-actions-row">
        <a
          className="od-cbtn"
          href={fromUnmatched ? '/admin/unmatched' : '/scan_management?active_tab=manual'}
        >
          Back to scan review
        </a>
      </div>
      {loadError ? (
        <PageStatus announcement="alert" className="od-manual-identify__error">
          {loadError} <Button onClick={() => window.location.reload()}>Retry</Button>
        </PageStatus>
      ) : null}
      {scanRunning ? (
        <PageStatus announcement="status" className="od-manual-identify__error">
          A scan is running. Editing is paused until it finishes.
        </PageStatus>
      ) : null}
      <section className="od-admin-panel" aria-labelledby="od-identify-search-title">
        <h2 id="od-identify-search-title">Search metadata</h2>
        <form className="od-manual-identify__search" onSubmit={search}>
          <label className="od-admin-field">
            Game name
            <input
              className="od-admin-input"
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
            />
          </label>
          <Button type="submit" disabled={searchBusy || !searchText.trim()}>
            {searchBusy ? `Searching ${searchSource}…` : 'Search IGDB'}
          </Button>
        </form>
        <div className="od-manual-identify__providers" aria-label="Other metadata providers">
          {['steam', 'gog', 'rawg', 'mobygames', 'thegamesdb'].map((source) => (
            <Button
              key={source}
              type="button"
              onClick={() => void searchProvider(source)}
              disabled={searchBusy || !searchText.trim()}
            >
              Search{' '}
              {source === 'thegamesdb'
                ? 'TheGamesDB'
                : source === 'mobygames'
                  ? 'MobyGames'
                  : source.toUpperCase()}
            </Button>
          ))}
        </div>
        {candidates.length ? (
          <ul className="od-manual-identify__results" aria-label={`${searchSource} matches`}>
            {candidates.map((row) => (
              <li key={row.id || row.url || row.name}>
                <span>
                  {row.name} · {searchSource} {row.id ? `#${row.id}` : ''}
                </span>
                <Button
                  type="button"
                  onClick={() => (searchSource === 'IGDB' ? choose(row) : void chooseProvider(row))}
                >
                  Use this match
                </Button>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
      <form className="od-admin-panel od-manual-identify__form" onSubmit={submit}>
        <h2>Game details</h2>
        <label className="od-admin-field">
          Library
          <select
            className="od-admin-input"
            value={form.library_uuid}
            onChange={(event) => setField('library_uuid', event.target.value)}
            required
            disabled={!options || saving}
          >
            {options?.libraries.map((row) => (
              <option key={row.uuid} value={row.uuid}>
                {row.name} · {row.platform_name}
              </option>
            ))}
          </select>
        </label>
        <label className="od-admin-field">
          IGDB ID
          <input
            className="od-admin-input"
            type="number"
            min="1"
            value={form.igdb_id}
            onChange={(event) => setField('igdb_id', event.target.value)}
            required
          />
        </label>
        <div className="od-admin-actions-row">
          <Button
            type="button"
            onClick={() => void loadIgdbId()}
            disabled={searchBusy || !form.igdb_id}
          >
            Load IGDB entry
          </Button>
          <Button type="button" onClick={() => void addNonCatalogGame()}>
            Add non-catalog game
          </Button>
        </div>
        <label className="od-admin-field">
          Name
          <input
            className="od-admin-input"
            value={form.name}
            onChange={(event) => setField('name', event.target.value)}
            required
          />
        </label>
        <label className="od-admin-field">
          Game folder path
          <input
            className="od-admin-input"
            value={form.full_disk_path}
            onChange={(event) => setField('full_disk_path', event.target.value)}
            required
          />
        </label>
        <label className="od-admin-field">
          Summary
          <textarea
            className="od-admin-input"
            rows={4}
            value={form.summary}
            onChange={(event) => setField('summary', event.target.value)}
          />
        </label>
        <label className="od-admin-field">
          Storyline
          <textarea
            className="od-admin-input"
            rows={4}
            value={form.storyline}
            onChange={(event) => setField('storyline', event.target.value)}
          />
        </label>
        <div className="od-manual-identify__grid">
          <label className="od-admin-field">
            Website
            <input
              className="od-admin-input"
              type="url"
              value={form.url}
              onChange={(event) => setField('url', event.target.value)}
            />
          </label>
          <label className="od-admin-field">
            First release date
            <input
              className="od-admin-input"
              type="date"
              value={form.first_release_date}
              onChange={(event) => setField('first_release_date', event.target.value)}
            />
          </label>
          <label className="od-admin-field">
            Aggregated rating
            <input
              className="od-admin-input"
              type="number"
              min="0"
              max="100"
              step="any"
              value={form.aggregated_rating}
              onChange={(event) => setField('aggregated_rating', event.target.value)}
            />
          </label>
          <label className="od-admin-field">
            Category
            <select
              className="od-admin-input"
              value={form.category}
              onChange={(event) => setField('category', event.target.value)}
            >
              <option value="">Select category</option>
              {options?.categories.map((row) => (
                <option key={row.value} value={row.value}>
                  {row.label}
                </option>
              ))}
            </select>
          </label>
          <label className="od-admin-field">
            Status
            <select
              className="od-admin-input"
              value={form.status}
              onChange={(event) => setField('status', event.target.value)}
            >
              <option value="">Select status</option>
              {options?.statuses.map((row) => (
                <option key={row.value} value={row.value}>
                  {row.label}
                </option>
              ))}
            </select>
          </label>
          <label className="od-admin-field">
            Developer
            <input
              className="od-admin-input"
              value={form.developer}
              onChange={(event) => setField('developer', event.target.value)}
            />
          </label>
          <label className="od-admin-field">
            Publisher
            <input
              className="od-admin-input"
              value={form.publisher}
              onChange={(event) => setField('publisher', event.target.value)}
            />
          </label>
          <label className="od-admin-field">
            Video URLs
            <input
              className="od-admin-input"
              value={form.video_urls}
              onChange={(event) => setField('video_urls', event.target.value)}
            />
          </label>
          <label className="od-admin-field">
            Item kind
            <select
              className="od-admin-input"
              value={form.item_kind}
              onChange={(event) => setField('item_kind', event.target.value)}
            >
              <option value="">Automatic</option>
              {['game', 'experience', 'emulator', 'tool'].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
        </div>
        <details className="od-manual-identify__provider-links">
          <summary>Provider links</summary>
          <div className="od-manual-identify__grid">
            {[
              ['steam', 'Steam'],
              ['gog', 'GOG'],
              ['epicgames', 'Epic Games'],
              ['itch', 'itch.io'],
              ['rawg', 'RAWG'],
              ['mobygames', 'MobyGames'],
              ['thegamesdb', 'TheGamesDB'],
              ['official', 'Official site'],
              ['wikipedia', 'Wikipedia'],
            ].map(([key, label]) => (
              <label className="od-admin-field" key={key}>
                {label}
                <input
                  className="od-admin-input"
                  type="url"
                  value={form.provider_urls[key] || ''}
                  onChange={(event) =>
                    setField('provider_urls', { ...form.provider_urls, [key]: event.target.value })
                  }
                  placeholder="https://…"
                />
              </label>
            ))}
          </div>
        </details>
        {TAXONOMIES.map(([key, label, field]) => (
          <fieldset className="od-manual-identify__taxonomy" key={key}>
            <legend>{label}</legend>
            {options?.taxonomies[key]?.map((row) => (
              <label key={row.id}>
                <input
                  type="checkbox"
                  checked={form[field].includes(row.id)}
                  onChange={(event) =>
                    setField(
                      field,
                      event.target.checked
                        ? [...form[field], row.id]
                        : form[field].filter((id: number) => id !== row.id),
                    )
                  }
                />{' '}
                {row.name}
              </label>
            ))}
          </fieldset>
        ))}
        {saveError ? (
          <PageStatus announcement="alert" className="od-manual-identify__error">
            {saveError}
          </PageStatus>
        ) : null}
        {Object.keys(fieldErrors).length ? (
          <ul className="od-manual-identify__error-list" aria-label="Field validation errors">
            {Object.entries(fieldErrors).map(([field, message]) => (
              <li key={field}>
                <strong>{field.replaceAll('_', ' ')}:</strong> {message}
              </li>
            ))}
          </ul>
        ) : null}
        <div className="od-admin-actions-row">
          <Button
            variant="primary"
            type="submit"
            disabled={saving || !options || Boolean(loadError) || scanRunning}
          >
            {saving ? 'Saving…' : editing ? 'Save changes' : 'Save and identify game'}
          </Button>
        </div>
      </form>
      <section className="od-admin-panel" aria-labelledby="od-link-existing-title">
        <h2 id="od-link-existing-title">Or link to an existing library game</h2>
        <p className="od-admin-lede">
          Search your library and choose a game to link this folder to instead of adding a new one.
        </p>
        <form className="od-admin-panel__toolbar" onSubmit={searchExistingGames}>
          <label className="od-admin-field">
            Search existing games
            <input
              className="od-admin-input"
              value={linkQuery}
              onChange={(event) => {
                setLinkQuery(event.target.value)
                setLinkHits([])
                setLinkSelected(null)
                setLinkError('')
                setLinkSearched(false)
              }}
              disabled={linkSearching || linkBusy}
              maxLength={100}
            />
          </label>
          <Button
            className="od-btn--secondary"
            type="submit"
            disabled={linkQuery.trim().length < 2 || linkSearching || linkBusy}
          >
            {linkSearching ? 'Searching…' : 'Search existing games'}
          </Button>
        </form>
        {linkError ? (
          <PageStatus error={linkError} errorMessage="Unable to link this folder." />
        ) : null}
        {linkHits.length ? (
          <div role="group" aria-label="Existing game search results">
            {linkHits.map((game) => (
              <Button
                key={game.uuid}
                type="button"
                className={
                  linkSelected?.uuid === game.uuid ? 'od-btn--accent' : 'od-btn--secondary'
                }
                aria-pressed={linkSelected?.uuid === game.uuid}
                onClick={() => setLinkSelected(game)}
                disabled={linkBusy}
              >
                {game.name}
                {game.full_disk_path ? ` · ${game.full_disk_path}` : ''}
              </Button>
            ))}
          </div>
        ) : null}
        {linkSearched && !linkHits.length ? (
          <PageStatus announcement="status">No existing games matched that search.</PageStatus>
        ) : null}
        <div className="od-admin-panel__toolbar">
          <Button
            className="od-btn--accent"
            type="button"
            onClick={() => void linkExistingGame()}
            disabled={!form.full_disk_path || !form.library_uuid || !linkSelected || linkBusy}
          >
            {linkBusy ? 'Linking…' : 'Link selected game'}
          </Button>
        </div>
      </section>
    </Page>
  )
}
