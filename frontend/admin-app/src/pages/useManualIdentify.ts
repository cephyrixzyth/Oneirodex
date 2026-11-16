import { confirmAction } from '@oneirodex/ui'
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { getJson, postJson, putJson } from '../api/adminApi'
import { Candidate, Options, providerName } from './manualIdentifyTypes'
type ManualIdentifyForm = {
  igdb_id: string | number
  name: string
  full_disk_path: string
  library_uuid: string
  summary: string
  storyline: string
  url: string
  video_urls: string
  first_release_date: string
  aggregated_rating: string | number
  category: string
  status: string
  developer: string
  publisher: string
  item_kind: string
  provider_urls: Record<string, string>
  genre_ids: number[]
  game_mode_ids: number[]
  theme_ids: number[]
  platform_ids: number[]
  player_perspective_ids: number[]
}

function suggestedNameFromPath(path: string, extensions: string[] = []) {
  const leaf = path.trim().split(/[\\/]/).filter(Boolean).at(-1) || ''
  const knownExtensions = new Set(
    extensions.map((extension) => {
      const normalized = extension.trim().toLowerCase()
      return normalized.startsWith('.') ? normalized : `.${normalized}`
    }),
  )
  let title = leaf
  for (let depth = 0; depth < 4; depth += 1) {
    const dot = title.lastIndexOf('.')
    if (dot <= 0 || !knownExtensions.has(title.slice(dot).toLowerCase())) break
    title = title.slice(0, dot)
  }
  return title
}
export function useManualIdentify() {
  const location = useLocation()
  const navigate = useNavigate()
  const { gameUuid } = useParams()
  const editing = Boolean(gameUuid)
  const query = useMemo(() => new URLSearchParams(location.search), [location.search])
  const [options, setOptions] = useState<Options | null>(null)
  const [loadError, setLoadError] = useState('')
  const [candidates, setCandidates] = useState<Candidate[]>([])
  const [providerNotice, setProviderNotice] = useState('')
  const [providerError, setProviderError] = useState('')
  const [searchBusy, setSearchBusy] = useState(false)
  const [searchSource, setSearchSource] = useState('IGDB')
  const [form, setForm] = useState<ManualIdentifyForm>({
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
  const [activeTab, setActiveTab] = useState('about')
  const [customIdMode, setCustomIdMode] = useState(false)
  const nameInputRef = useRef<HTMLInputElement>(null)

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
          name:
            current.name ||
            (!editing ? suggestedNameFromPath(current.full_disk_path, data.file_extensions) : ''),
          library_uuid: current.library_uuid || data.libraries[0]?.uuid || '',
          category: current.category || data.categories?.[0]?.value || '',
          status: current.status || data.statuses?.[0]?.value || '',
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
        const editableGame = { ...payload.game }
        delete editableGame.uuid
        setForm((current) => ({ ...current, ...editableGame }))
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

  async function search() {
    const term = String(form.name || '').trim()
    if (searchBusy || customIdMode) return
    if (!term) {
      setSearchSource('IGDB')
      setSaveError('')
      setCandidates([])
      setProviderNotice('Enter a game name first')
      setProviderError('')
      return
    }
    setSearchBusy(true)
    setSearchSource('IGDB')
    setSaveError('')
    setProviderNotice('')
    setProviderError('')
    try {
      const params = new URLSearchParams({ name: term })
      const data = await getJson(`/api/search_igdb_by_name?${params}`)
      setCandidates(Array.isArray(data.results) ? data.results : [])
      if (!Array.isArray(data.results) || !data.results.length)
        setProviderNotice('No IGDB matches found. You can still enter the metadata manually.')
    } catch (error) {
      setProviderError(error instanceof Error ? error.message : 'IGDB search failed.')
    } finally {
      setSearchBusy(false)
    }
  }

  async function searchProvider(source: string) {
    const term = String(form.name || '').trim()
    if (searchBusy) return
    if (!term) {
      setSearchSource(providerName(source))
      setSaveError('')
      setCandidates([])
      setProviderNotice('Enter a game name first')
      setProviderError('')
      return
    }
    setSearchBusy(true)
    setSearchSource(providerName(source))
    setSaveError('')
    setProviderNotice('')
    setProviderError('')
    try {
      const params = new URLSearchParams({ name: term, source })
      const data = await getJson(`/api/search_metadata?${params}`)
      setCandidates(Array.isArray(data.results) ? data.results : [])
      if (!Array.isArray(data.results) || !data.results.length)
        setProviderNotice(data.note || `No ${providerName(source)} matches found.`)
    } catch (error) {
      setProviderError(
        error instanceof Error ? error.message : `${providerName(source)} search failed.`,
      )
    } finally {
      setSearchBusy(false)
    }
  }

  async function chooseProvider(row: Candidate) {
    setProviderNotice('')
    setProviderError('')
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
      setProviderNotice(
        `Applied ${searchSource.toUpperCase()} match (custom IGDB ID). Save to keep.`,
      )
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
      const destination = payload.redirect_url || '/library'
      if (destination === '/library') {
        // /library belongs to the member SPA. Leave the admin router so the
        // server can hand the request to the correct application shell.
        window.location.assign(destination)
      } else {
        navigate(destination)
      }
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
  const hasScanContext = fromUnmatched || query.has('full_disk_path')
  const identifyFieldsValid =
    /^\d+$/.test(String(form.igdb_id).trim()) &&
    Number(form.igdb_id) > 0 &&
    String(form.full_disk_path).trim().length > 0 &&
    String(form.name).trim().length > 0
  const tabs = [
    ['about', 'About'],
    ['release', 'Release'],
    ['links', 'Links & media'],
    ['taxonomy', 'Taxonomy'],
  ] as const
  function onTabKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = tabs.findIndex(([id]) => id === activeTab)
    let next = -1
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length
    if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length
    if (event.key === 'Home') next = 0
    if (event.key === 'End') next = tabs.length - 1
    if (next < 0) return
    event.preventDefault()
    setActiveTab(tabs[next][0])
    event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[next]?.focus()
  }
  async function loadIgdbId() {
    const id = Number(form.igdb_id)
    if (!Number.isInteger(id) || id < 1 || searchBusy || customIdMode) return
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
      setCustomIdMode(true)
      setField('name', '')
      setField('item_kind', 'game')
      requestAnimationFrame(() => nameInputRef.current?.focus())
    } catch {
      setSaveError('Could not allocate a custom catalog ID. Try again.')
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
      navigate('/scan_management?active_tab=unmatched', {
        state: { linkSuccess: `Linked existing game '${linkSelected.name}' to this folder.` },
      })
    } catch (error) {
      setLinkError(error instanceof Error ? error.message : 'Unable to link this folder.')
    } finally {
      setLinkBusy(false)
    }
  }
  return {
    editing,
    options,
    loadError,
    candidates,
    providerNotice,
    providerError,
    searchBusy,
    searchSource,
    form,
    saving,
    saveError,
    fieldErrors,
    scanRunning,
    linkQuery,
    setLinkQuery,
    linkHits,
    setLinkHits,
    linkSelected,
    setLinkSelected,
    linkSearching,
    linkBusy,
    linkError,
    setLinkError,
    linkSearched,
    setLinkSearched,
    activeTab,
    setActiveTab,
    customIdMode,
    nameInputRef,
    setField,
    search,
    searchProvider,
    chooseProvider,
    choose,
    submit,
    fromUnmatched,
    hasScanContext,
    identifyFieldsValid,
    tabs,
    onTabKeyDown,
    loadIgdbId,
    addNonCatalogGame,
    searchExistingGames,
    linkExistingGame,
  }
}
