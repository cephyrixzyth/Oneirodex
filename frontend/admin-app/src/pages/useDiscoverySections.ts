import { useEffect, useRef, useState, type FormEvent } from 'react'
import { confirmAction } from '@oneirodex/ui'
import { getJson, postJson, putJson, deleteJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'

export const API = '/admin/api/discovery_sections'
type Shelf = {
  id: number
  name: string
  section_type: string
  is_visible: boolean
  count: number
  description: string
  config: { mode?: string; filter_type?: string; filter_value?: string; game_uuids?: string[] }
  layout: string
  starts_at: string | null
  ends_at: string | null
  pin_rank: number | null
  is_live: boolean
}
type Pick = { uuid: string; name: string }
type DiscoveryOptions = {
  libraries: Pick[]
  platforms: { id: string; label: string }[]
  genres: { name: string }[]
}
type Editor = {
  id?: number
  name: string
  mode: string
  filter_type: string
  filter_value: string
  picks: Pick[]
}
export function utcInput(value: string | null) {
  return value ? value.replace(/Z$/, '').slice(0, 19) : ''
}

export function useDiscoverySections() {
  const [sections, setSections] = useState<Shelf[]>([])
  const [options, setOptions] = useState<DiscoveryOptions>({
    libraries: [],
    platforms: [],
    genres: [],
  })
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [editor, setEditor] = useState<Editor | null>(null)
  const [schedule, setSchedule] = useState<Shelf | null>(null)
  const [scheduleDraft, setScheduleDraft] = useState({
    layout: 'shelf',
    starts: '',
    ends: '',
    pin: '',
  })
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<Pick[] | null>(null)
  const [searching, setSearching] = useState(false)
  const searchRequest = useRef(0)
  function accept(data: Record<string, unknown>) {
    if (
      !Array.isArray(data.sections) ||
      !Array.isArray(data.libraries) ||
      !Array.isArray(data.platforms) ||
      !Array.isArray(data.genres)
    )
      throw new Error('Discovery sections returned an invalid response.')
    setSections(data.sections as Shelf[])
    setOptions({
      libraries: data.libraries as Pick[],
      platforms: data.platforms as DiscoveryOptions['platforms'],
      genres: data.genres as DiscoveryOptions['genres'],
    })
  }
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadFailed(false)
    setError('')
    getJson(API)
      .then((data) => {
        if (!cancelled) accept(data)
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
      searchRequest.current += 1
    }
  }, [reload])
  async function action(work: () => Promise<void>, confirm?: () => Promise<boolean>) {
    if (loading || loadFailed || lock.current) return
    lock.current = true
    setError('')
    setMessage('')
    try {
      if (confirm && !(await confirm())) return
      setBusy(true)
      await work()
    } catch (err) {
      setError(errorText(err) || 'Could not complete the action.')
    } finally {
      lock.current = false
      setBusy(false)
    }
  }
  async function refresh() {
    try {
      accept(await getJson(API))
    } catch (err) {
      setLoadFailed(true)
      throw err
    }
  }
  function openEditor(row?: Shelf) {
    setError('')
    setMessage('')
    setQuery('')
    setHits(null)
    searchRequest.current += 1
    setSearching(false)
    const config = row?.config || {}
    setEditor({
      id: row?.id,
      name: row?.name || '',
      mode: config.mode || 'manual',
      filter_type: config.filter_type || 'library',
      filter_value: config.filter_value || options.libraries[0]?.uuid || '',
      picks: (config.game_uuids || []).map((uuid: string) => ({ uuid, name: uuid })),
    })
  }
  function closeEditor() {
    if (!busy) {
      setEditor(null)
      searchRequest.current += 1
      setSearching(false)
      setError('')
    }
  }
  async function search() {
    if (!query.trim() || searching || busy) return
    const request = ++searchRequest.current
    setSearching(true)
    setError('')
    try {
      const data = await getJson(`/api/search?query=${encodeURIComponent(query.trim())}`)
      if (request !== searchRequest.current) return
      if (!Array.isArray(data)) throw new Error('Game search returned an invalid response.')
      setHits(data.slice(0, 12).map((row) => ({ uuid: row.uuid, name: row.name || row.uuid })))
    } catch (err) {
      if (request === searchRequest.current) setError(errorText(err))
    } finally {
      if (request === searchRequest.current) setSearching(false)
    }
  }
  function saveShelf(event: FormEvent) {
    event.preventDefault()
    if (!editor) return
    void action(async () => {
      const payload = {
        name: editor.name.trim(),
        mode: editor.mode,
        ...(editor.mode === 'manual'
          ? { game_uuids: editor.picks.map((row) => row.uuid) }
          : { filter_type: editor.filter_type, filter_value: editor.filter_value }),
      }
      if (editor.id) await putJson(`${API}/${editor.id}`, payload)
      else await postJson(API, payload)
      setEditor(null)
      searchRequest.current += 1
      setSearching(false)
      await refresh()
      setMessage('Shelf saved.')
    })
  }
  function move(index: number, offset: number) {
    const next = [...sections]
    const to = index + offset
    if (to < 0 || to >= next.length) return
    ;[next[index], next[to]] = [next[to], next[index]]
    void action(async () => {
      await postJson(`${API}/order`, {
        sections: next.map((row, order) => ({ id: row.id, order })),
      })
      setSections(next)
      setMessage('Shelf order saved.')
    })
  }
  function remove(row: Shelf) {
    void action(
      async () => {
        await deleteJson(`${API}/${row.id}`)
        setSections((current) => current.filter((item) => item.id !== row.id))
        setMessage('Shelf deleted.')
      },
      () =>
        confirmAction({
          title: 'Delete this shelf?',
          body: `Delete discovery shelf "${row.name}"? This cannot be undone.`,
          confirmLabel: 'Delete shelf',
          cancelLabel: 'Keep shelf',
        }),
    )
  }
  const disabled = loading || loadFailed || busy
  const filterOptions = !editor
    ? []
    : editor.filter_type === 'library'
      ? options.libraries.map((row) => ({ value: row.uuid, label: row.name }))
      : editor.filter_type === 'platform'
        ? options.platforms.map((row) => ({ value: row.id, label: row.label }))
        : options.genres.map((row) => ({ value: row.name, label: row.name }))
  function edit(patch: Partial<Editor>) {
    setEditor((current) => (current ? { ...current, ...patch } : null))
    setMessage('')
  }

  return {
    sections,
    setSections,
    options,
    setOptions,
    loading,
    setLoading,
    loadFailed,
    setLoadFailed,
    reload,
    setReload,
    busy,
    setBusy,
    lock,
    error,
    setError,
    message,
    setMessage,
    editor,
    setEditor,
    schedule,
    setSchedule,
    scheduleDraft,
    setScheduleDraft,
    query,
    setQuery,
    hits,
    setHits,
    searching,
    setSearching,
    searchRequest,
    accept,
    action,
    refresh,
    openEditor,
    closeEditor,
    search,
    saveShelf,
    move,
    remove,
    disabled,
    filterOptions,
    edit,
    API,
  }
}
