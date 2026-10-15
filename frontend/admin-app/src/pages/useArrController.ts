import { useEffect, useState, type FormEvent } from 'react'
import { confirmAction } from '@oneirodex/ui'
import { deleteJson, getJson, postJson, putJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'

type Indexer = {
  id: string
  name: string
  protocol: string
  url: string
  ready: boolean
  enabled: boolean
  source: string
  api_key_set?: boolean
}
type Preset = { id: string; name: string; protocol?: string; notes?: string }
type Hit = {
  title: string
  indexer?: string
  seeders?: number
  size?: number
  download_url?: string
  quality?: { score?: number; allowed?: boolean; reasons?: string[] }
}
type Proposal = {
  name?: string
  source?: string
  dest?: string
  preview?: { would_succeed?: boolean; reasons?: string[] }
}
type Config = Record<string, string>
const URL_FIELDS = [
  'prowlarr_url',
  'jackett_url',
  'qbittorrent_url',
  'transmission_url',
  'sabnzbd_url',
  'nzbget_url',
] as const
const SECRET_FIELDS = [
  'prowlarr_api_key',
  'jackett_api_key',
  'qbittorrent_password',
  'transmission_password',
  'sabnzbd_api_key',
  'nzbget_password',
] as const
const USER_FIELDS = ['qbittorrent_username', 'transmission_username', 'nzbget_username'] as const
export const LABELS: Record<string, string> = {
  prowlarr_url: 'Prowlarr URL',
  jackett_url: 'Jackett URL',
  qbittorrent_url: 'qBittorrent URL',
  transmission_url: 'Transmission URL',
  sabnzbd_url: 'SABnzbd URL',
  nzbget_url: 'NZBGet URL',
  qbittorrent_username: 'qBittorrent username',
  transmission_username: 'Transmission username',
  nzbget_username: 'NZBGet username',
  prowlarr_api_key: 'Prowlarr API key',
  jackett_api_key: 'Jackett API key',
  qbittorrent_password: 'qBittorrent password',
  transmission_password: 'Transmission password',
  sabnzbd_api_key: 'SABnzbd API key',
  nzbget_password: 'NZBGet password',
}

function arrConfig(data: Record<string, unknown>): {
  draft: Config
  secrets: Record<string, boolean>
} {
  if (URL_FIELDS.some((key) => typeof data[key] !== 'string'))
    throw new Error('Arr connector settings returned an invalid response.')
  const draft: Config = {}
  const secrets: Record<string, boolean> = {}
  for (const key of URL_FIELDS) draft[key] = typeof data[key] === 'string' ? data[key] : ''
  for (const key of USER_FIELDS) draft[key] = typeof data[key] === 'string' ? data[key] : ''
  for (const key of SECRET_FIELDS) {
    const presenceKey = key.endsWith('_api_key')
      ? `${key}_set`
      : `${key.replace(/_password$/, '')}_password_set`
    secrets[key] = Boolean(data[presenceKey])
    draft[key] = ''
  }
  return { draft, secrets }
}

export function useArrController() {
  const [effectiveEnabled, setEffectiveEnabled] = useState(false)
  const [envEnabled, setEnvEnabled] = useState(false)
  const [moduleDraft, setModuleDraft] = useState(false)
  const [indexers, setIndexers] = useState<Indexer[]>([])
  const [presets, setPresets] = useState<Preset[]>([])
  const [selectedPresets, setSelectedPresets] = useState<string[]>([])
  const [bulkText, setBulkText] = useState('')
  const [config, setConfig] = useState<Config>({})
  const [secretPresence, setSecretPresence] = useState<Record<string, boolean>>({})
  const [connectors, setConnectors] = useState<any[]>([])
  const [indexerWarnings, setIndexerWarnings] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<Hit[]>([])
  const [searchWarnings, setSearchWarnings] = useState<string[]>([])
  const [excluded, setExcluded] = useState(0)
  const [hardlinkDest, setHardlinkDest] = useState('')
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [applyAllowed, setApplyAllowed] = useState(false)
  const [pipelineEnabled, setPipelineEnabled] = useState(false)
  const [helpersEnabled, setHelpersEnabled] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [reload, setReload] = useState(0)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadFailed(false)
    setError('')
    getJson('/api/arr/module')
      .then(async (module: { enabled?: unknown; db_enabled?: unknown; env_enabled?: unknown }) => {
        if (
          !module ||
          typeof module.enabled !== 'boolean' ||
          typeof module.db_enabled !== 'boolean' ||
          typeof module.env_enabled !== 'boolean'
        )
          throw new Error('Arr module status returned an invalid response.')
        if (cancelled) return
        setEffectiveEnabled(module.enabled)
        setModuleDraft(module.db_enabled)
        setEnvEnabled(module.env_enabled)
        if (!module.enabled) return
        const [status, indexerData, configData] = await Promise.all([
          getJson('/api/arr/status'),
          getJson('/api/arr/indexers'),
          getJson('/api/arr/config'),
        ])
        if (cancelled) return
        if (
          !Array.isArray(status?.connectors) ||
          !Array.isArray(indexerData?.indexers) ||
          !Array.isArray(indexerData?.presets)
        )
          throw new Error('Arr module returned an invalid connector or indexer list.')
        const next = arrConfig(configData)
        setConnectors(status.connectors)
        setIndexerWarnings(Array.isArray(status.indexer_warnings) ? status.indexer_warnings : [])
        setPipelineEnabled(Boolean(status.hardlink_pipeline_enabled))
        setHelpersEnabled(Boolean(status.hardlink_helpers_enabled))
        setApplyAllowed(Boolean(status.hardlink_apply_allowed))
        setIndexers(indexerData.indexers)
        setPresets(indexerData.presets)
        setConfig(next.draft)
        setSecretPresence(next.secrets)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorText(err) || 'Unable to load Arr settings.')
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

  function begin(label: string) {
    if (loading || loadFailed || busy) return false
    setBusy(true)
    setError('')
    setMessage('')
    if (label) setMessage(label)
    return true
  }
  function end() {
    setBusy(false)
  }

  async function saveModule(event: FormEvent) {
    event.preventDefault()
    if (!begin('Saving module preference…')) return
    try {
      const data = await putJson('/api/arr/module', { enabled: moduleDraft })
      setEffectiveEnabled(Boolean(data.enabled))
      setEnvEnabled(Boolean(data.env_enabled))
      setMessage(`Saved. Effective status: ${data.enabled ? 'on' : 'off'}.`)
      setReload((value) => value + 1)
    } catch (err) {
      setError(errorText(err) || 'Unable to save Arr module preference.')
    } finally {
      end()
    }
  }

  async function saveConnectors(event: FormEvent) {
    event.preventDefault()
    if (!begin('Saving connector settings…')) return
    const body: Config = { ...config }
    for (const key of SECRET_FIELDS) {
      if (!config[key]?.trim()) delete body[key]
    }
    try {
      const data = await putJson('/api/arr/config', body)
      const next = arrConfig(data.config)
      setConfig(next.draft)
      setSecretPresence(next.secrets)
      setMessage('Connector settings saved. Blank secret fields kept their saved values.')
    } catch (err) {
      setError(errorText(err) || 'Unable to save connector settings.')
    } finally {
      end()
    }
  }

  async function refreshIndexers() {
    const data = await getJson('/api/arr/indexers')
    if (!Array.isArray(data?.indexers) || !Array.isArray(data?.presets))
      throw new Error('Indexer registry returned an invalid response.')
    setIndexers(data.indexers)
    setPresets(data.presets)
  }

  async function addIndexer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const fd = new FormData(form)
    if (!begin('Adding indexer…')) return
    try {
      await postJson('/api/arr/indexers', {
        name: fd.get('name'),
        protocol: fd.get('protocol'),
        url: fd.get('url'),
        api_key: fd.get('api_key'),
        enabled: true,
      })
      form.reset()
      await refreshIndexers()
      setMessage('Indexer added.')
    } catch (err) {
      setError(errorText(err) || 'Unable to add indexer.')
    } finally {
      end()
    }
  }

  async function bulkImport() {
    const raw = bulkText.trim()
    if (!raw) {
      setError('Paste JSON or CSV first.')
      return
    }
    let body: unknown
    try {
      body = JSON.parse(raw)
    } catch {
      body = { text: raw }
    }
    if (!begin('Importing indexers…')) return
    try {
      const result = await postJson('/api/arr/indexers/bulk', body)
      setBulkText('')
      await refreshIndexers()
      setMessage(`Imported ${result.count || 0} indexer(s).`)
    } catch (err) {
      setError(errorText(err) || 'Unable to import indexers.')
    } finally {
      end()
    }
  }

  async function enablePresets() {
    if (!selectedPresets.length) {
      setError('Select at least one preset.')
      return
    }
    if (!begin('Enabling selected presets…')) return
    try {
      const result = await postJson('/api/arr/indexers/enable-presets', {
        preset_ids: selectedPresets,
      })
      setSelectedPresets([])
      await refreshIndexers()
      setMessage(
        `Enabled ${result.count || 0} preset(s). Add real URLs and API keys before searching.`,
      )
    } catch (err) {
      setError(errorText(err) || 'Unable to enable presets.')
    } finally {
      end()
    }
  }

  async function toggleIndexer(row: Indexer, enabled: boolean) {
    if (!begin('Updating indexer…')) return
    try {
      await putJson(`/api/arr/indexers/${encodeURIComponent(row.id)}`, { enabled })
      await refreshIndexers()
      setMessage('Indexer updated.')
    } catch (err) {
      setError(errorText(err) || 'Unable to update indexer.')
    } finally {
      end()
    }
  }

  async function removeIndexer(row: Indexer) {
    if (
      !(await confirmAction({
        title: `Delete ${row.name}?`,
        body: 'This removes the indexer from the native registry.',
        confirmLabel: 'Delete indexer',
        tone: 'danger',
      }))
    )
      return
    if (!begin('Deleting indexer…')) return
    try {
      await deleteJson(`/api/arr/indexers/${encodeURIComponent(row.id)}`)
      await refreshIndexers()
      setMessage('Indexer deleted.')
    } catch (err) {
      setError(errorText(err) || 'Unable to delete indexer.')
    } finally {
      end()
    }
  }

  async function search() {
    const term = query.trim()
    if (!term) {
      setError('Enter a title to search.')
      return
    }
    if (!begin('Searching configured indexers…')) return
    try {
      const data = await getJson(`/api/arr/search?q=${encodeURIComponent(term)}`)
      if (!Array.isArray(data.results))
        throw new Error('Indexer search returned an invalid result list.')
      setHits(data.results)
      setSearchWarnings(Array.isArray(data.warnings) ? data.warnings : [])
      setExcluded(Number(data.excluded_by_quality) || 0)
      setMessage(
        data.results.length
          ? `${data.results.length} result(s) found.`
          : 'No results matched the active quality profile.',
      )
    } catch (err) {
      setError(errorText(err) || 'Indexer search failed.')
    } finally {
      end()
    }
  }

  async function sendToClient(hit: Hit) {
    if (!hit.download_url) {
      setError('This result does not include a download link.')
      return
    }
    if (
      !(await confirmAction({
        title: 'Send this result to qBittorrent?',
        body: `This contacts your configured download client and adds “${hit.title}” to its queue. Review the result and your ownership rights first.`,
        confirmLabel: 'Add to qBittorrent',
      }))
    )
      return
    if (!begin('Sending result to qBittorrent…')) return
    try {
      await postJson('/api/arr/download', { download_url: hit.download_url })
      setMessage('Result sent to qBittorrent.')
    } catch (err) {
      setError(errorText(err) || 'Unable to send result to qBittorrent.')
    } finally {
      end()
    }
  }

  async function previewHardlinks() {
    const dest = hardlinkDest.trim()
    if (!dest) {
      setError('Choose an existing library destination directory.')
      return
    }
    if (!begin('Previewing completed downloads…')) return
    try {
      const data = await postJson('/api/arr/hardlink/preview', { library_dest_dir: dest })
      if (!Array.isArray(data.proposals))
        throw new Error('Hardlink preview returned an invalid proposal list.')
      setProposals(data.proposals)
      setApplyAllowed(Boolean(data.apply_allowed))
      setMessage(
        `${data.count || data.proposals.length} completed download(s) previewed. No files were changed.`,
      )
    } catch (err) {
      setError(errorText(err) || 'Unable to preview hardlinks.')
    } finally {
      end()
    }
  }

  async function applyHardlinks() {
    const safeCount = proposals.filter((item) => item.preview?.would_succeed).length
    if (!safeCount) {
      setError('Preview must contain at least one allowed proposal before applying.')
      return
    }
    if (!applyAllowed) {
      setError('Hardlink apply is disabled by the current environment gates.')
      return
    }
    if (
      !(await confirmAction({
        title: `Create ${safeCount} hardlink${safeCount === 1 ? '' : 's'}?`,
        body: 'This writes links into the selected library folder. Only previewed, successful proposals will be applied; verify every source and destination before continuing.',
        confirmLabel: 'Apply hardlinks',
        tone: 'danger',
      }))
    )
      return
    if (!begin('Applying previewed hardlinks…')) return
    try {
      const result = await postJson('/api/arr/hardlink/apply', { proposals, only_ok: true })
      setProposals([])
      setMessage(
        `Hardlink operation finished: ${result.applied?.length || 0} applied, ${result.skipped?.length || 0} skipped.`,
      )
    } catch (err) {
      setError(errorText(err) || 'Unable to apply hardlinks.')
    } finally {
      end()
    }
  }

  const disabled = loading || loadFailed || busy

  return {
    effectiveEnabled,
    setEffectiveEnabled,
    envEnabled,
    setEnvEnabled,
    moduleDraft,
    setModuleDraft,
    indexers,
    setIndexers,
    presets,
    setPresets,
    selectedPresets,
    setSelectedPresets,
    bulkText,
    setBulkText,
    config,
    setConfig,
    secretPresence,
    setSecretPresence,
    connectors,
    setConnectors,
    indexerWarnings,
    setIndexerWarnings,
    query,
    setQuery,
    hits,
    setHits,
    searchWarnings,
    setSearchWarnings,
    excluded,
    setExcluded,
    hardlinkDest,
    setHardlinkDest,
    proposals,
    setProposals,
    applyAllowed,
    setApplyAllowed,
    pipelineEnabled,
    setPipelineEnabled,
    helpersEnabled,
    setHelpersEnabled,
    loading,
    setLoading,
    loadFailed,
    setLoadFailed,
    busy,
    setBusy,
    reload,
    setReload,
    error,
    setError,
    message,
    setMessage,
    begin,
    end,
    saveModule,
    saveConnectors,
    refreshIndexers,
    addIndexer,
    bulkImport,
    enablePresets,
    toggleIndexer,
    removeIndexer,
    search,
    sendToClient,
    previewHardlinks,
    applyHardlinks,
    disabled,
    URL_FIELDS,
    SECRET_FIELDS,
    USER_FIELDS,
  }
}
