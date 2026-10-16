import { useEffect, useState, type FormEvent } from 'react'
import { Button, PageStatus, confirmAction } from '@oneirodex/ui'
import { Page } from '../components/Page'
import { getJson, postJson, putJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import './AiAssistPage.css'

type Config = {
  enabled: boolean
  db_enabled: boolean
  env_enabled: boolean
  ollama_base_url: string
  ollama_model: string
  auto_apply_enabled: boolean
}
type AiStatus = {
  enabled: boolean
  auto_apply_enabled: boolean
  reachable: boolean
  model: string
  error?: string
}
type Suggestion = { rank?: number; title: string }

function configFrom(data: Partial<Config> & Record<string, unknown>): Config {
  if (
    !data ||
    ['enabled', 'db_enabled', 'env_enabled', 'auto_apply_enabled'].some(
      (key) => typeof data[key] !== 'boolean',
    ) ||
    typeof data.ollama_base_url !== 'string' ||
    typeof data.ollama_model !== 'string'
  ) {
    throw new Error('AI Assist returned an invalid configuration.')
  }
  return data as Config
}

export function AiAssistPage() {
  const [config, setConfig] = useState<Config | null>(null)
  const [enabled, setEnabled] = useState(false)
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [status, setStatus] = useState<AiStatus | null>(null)
  const [name, setName] = useState('')
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [gameUuid, setGameUuid] = useState('')
  const [applyTitle, setApplyTitle] = useState('')
  const [doctorUuid, setDoctorUuid] = useState('')
  const [issues, setIssues] = useState('')
  const [output, setOutput] = useState('')
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
    getJson('/api/ai/config')
      .then((data) => {
        const next = configFrom(data)
        if (cancelled) return
        setConfig(next)
        setEnabled(next.db_enabled)
        setBaseUrl(next.ollama_base_url)
        setModel(next.ollama_model)
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorText(err) || 'Unable to load AI Assist settings.')
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

  async function save(event: FormEvent) {
    event.preventDefault()
    if (loading || loadFailed || busy) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const next = configFrom(
        await putJson('/api/ai/config', {
          enabled,
          ollama_base_url: baseUrl.trim(),
          ollama_model: model.trim(),
        }),
      )
      setConfig(next)
      setEnabled(next.db_enabled)
      setBaseUrl(next.ollama_base_url)
      setModel(next.ollama_model)
      setStatus(null)
      setMessage('AI Assist settings saved.')
    } catch (err) {
      setError(errorText(err) || 'Unable to save AI Assist settings.')
    } finally {
      setBusy(false)
    }
  }

  async function testConnection() {
    if (loading || loadFailed || busy) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const next = (await getJson('/api/ai/status')) as AiStatus
      if (!next || typeof next.reachable !== 'boolean' || typeof next.enabled !== 'boolean')
        throw new Error('AI connection check returned an invalid response.')
      setStatus(next)
      setMessage(next.reachable ? 'Ollama responded.' : next.error || 'Ollama is not reachable.')
    } catch (err) {
      setError(errorText(err) || 'Unable to check the Ollama connection.')
    } finally {
      setBusy(false)
    }
  }

  async function runAction(label: string, work: () => Promise<unknown>) {
    if (loading || loadFailed || busy || !config?.enabled) return
    setBusy(true)
    setError('')
    setMessage('')
    setOutput('')
    try {
      const result = await work()
      setOutput(JSON.stringify(result, null, 2))
      setMessage(label)
      return result
    } catch (err) {
      setError(errorText(err) || `${label} failed.`)
      return null
    } finally {
      setBusy(false)
    }
  }

  async function triage() {
    const term = name.trim()
    if (!term) {
      setError('Enter a folder or game title first.')
      return
    }
    const result = (await runAction('Suggestions loaded.', () =>
      postJson('/api/ai/triage', { name: term }),
    )) as { suggestions?: Suggestion[] }
    const next = Array.isArray(result?.suggestions)
      ? result.suggestions.filter((item) => typeof item?.title === 'string')
      : []
    setSuggestions(next)
    if (next[0]?.title) setApplyTitle(next[0].title)
  }

  async function applySuggestion() {
    const uuid = gameUuid.trim()
    const title = applyTitle.trim()
    if (!uuid || !title) {
      setError('Enter both an existing game UUID and the title to apply.')
      return
    }
    if (
      !(await confirmAction({
        title: 'Apply this game title?',
        body: `This changes the name of the existing game ${uuid}. Review the selected suggestion before continuing.`,
        confirmLabel: 'Apply title',
        tone: 'danger',
      }))
    )
      return
    await runAction('Title applied.', () =>
      postJson('/api/ai/apply-triage', { game_uuid: uuid, title }),
    )
  }

  async function doctorNotes() {
    const issueCodes = issues
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean)
    if (!issueCodes.length && !doctorUuid.trim()) {
      setError('Enter a game UUID or at least one issue code.')
      return
    }
    await runAction('Issue explanation loaded.', () =>
      postJson('/api/ai/doctor-notes', {
        ...(doctorUuid.trim() ? { game_uuid: doctorUuid.trim() } : {}),
        issues: issueCodes,
      }),
    )
  }

  const disabled = loading || loadFailed || busy
  return (
    <Page
      title="AI assist"
      lede="Ollama suggestions for game matching and metadata triage. Suggestions do not change games unless an administrator confirms an apply action."
    >
      <PageStatus
        loading={loading}
        loadingMessage="Loading AI Assist settings…"
        error={loadFailed ? error : null}
      />
      {loadFailed ? (
        <Button onClick={() => setReload((value) => value + 1)}>Retry loading settings</Button>
      ) : null}
      {error && !loadFailed ? (
        <PageStatus announcement="alert" className="od-ai-assist__error">
          {error}
        </PageStatus>
      ) : null}
      {message ? (
        <PageStatus announcement="status" className="od-admin-hint">
          {message}
        </PageStatus>
      ) : null}
      {config ? (
        <>
          <form className="od-admin-panel od-ai-assist__panel" onSubmit={save}>
            <h2>Module and Ollama</h2>
            <p className="od-admin-hint">
              Enable here or with <code>ENABLE_AI_ASSIST=true</code>. Environment status:{' '}
              <strong>{config.env_enabled ? 'on' : 'off'}</strong>. AI auto-apply remains
              environment-gated.
            </p>
            <fieldset className="od-admin-fieldset" disabled={disabled}>
              <label className="od-admin-check">
                <input
                  type="checkbox"
                  checked={enabled}
                  onChange={(e) => setEnabled(e.target.checked)}
                />{' '}
                Enable AI Assist (admin toggle)
              </label>
              <label className="od-admin-field">
                Ollama base URL
                <input
                  className="od-admin-input"
                  type="url"
                  autoComplete="url"
                  value={baseUrl}
                  placeholder="http://127.0.0.1:11434"
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
              </label>
              <label className="od-admin-field">
                Ollama model
                <input
                  className="od-admin-input"
                  value={model}
                  placeholder="llama3.2"
                  onChange={(e) => setModel(e.target.value)}
                />
              </label>
            </fieldset>
            <div className="od-admin-actions-row">
              <Button variant="primary" type="submit" disabled={disabled}>
                {busy ? 'Working…' : 'Save settings'}
              </Button>
              <Button disabled={disabled} onClick={() => void testConnection()}>
                Test connection
              </Button>
            </div>
            <PageStatus announcement="status" className="od-admin-hint">
              Effective status: {config.enabled ? 'on' : 'off'}
              {status
                ? ` · Ollama ${status.reachable ? 'reachable' : 'unreachable'} · model ${status.model || '—'}`
                : ''}
            </PageStatus>
            {status?.error ? <p className="od-ai-assist__error">{status.error}</p> : null}
            {!config.auto_apply_enabled ? (
              <p className="od-admin-hint">
                Rename apply is disabled until <code>ENABLE_AI_AUTO_APPLY=true</code> is configured.
              </p>
            ) : null}
          </form>
          <section
            className="od-admin-panel od-ai-assist__panel"
            aria-labelledby="od-ai-triage-title"
          >
            <h2 id="od-ai-triage-title">Suggest game matches</h2>
            <label className="od-admin-field">
              Folder or title
              <input
                className="od-admin-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Celeste"
              />
            </label>
            <Button
              variant="primary"
              disabled={disabled || !config.enabled}
              onClick={() => void triage()}
            >
              {busy ? 'Working…' : 'Suggest matches'}
            </Button>
            {suggestions.length ? (
              <ol className="od-ai-assist__suggestions">
                {suggestions.map((item, index) => (
                  <li key={`${item.title}-${index}`}>
                    <Button
                      className="od-ai-assist__suggestion"
                      disabled={disabled}
                      onClick={() => setApplyTitle(item.title)}
                    >
                      {item.title}
                    </Button>
                  </li>
                ))}
              </ol>
            ) : null}
            {!config.enabled ? (
              <p className="od-admin-hint">Enable AI Assist to request suggestions.</p>
            ) : null}
          </section>
          <section
            className="od-admin-panel od-ai-assist__panel"
            aria-labelledby="od-ai-apply-title"
          >
            <h2 id="od-ai-apply-title">Apply a selected title</h2>
            <p className="od-admin-hint">
              Applies only to an existing game. This action is disabled unless the environment
              setting enables AI auto-apply.
            </p>
            <label className="od-admin-field">
              Existing game UUID
              <input
                className="od-admin-input"
                value={gameUuid}
                onChange={(e) => setGameUuid(e.target.value)}
                placeholder="Game UUID"
              />
            </label>
            <label className="od-admin-field">
              Title to apply
              <input
                className="od-admin-input"
                value={applyTitle}
                onChange={(e) => setApplyTitle(e.target.value)}
                placeholder="Clean game title"
              />
            </label>
            <Button
              variant="danger"
              disabled={disabled || !config.enabled || !config.auto_apply_enabled}
              onClick={() => void applySuggestion()}
            >
              Apply title…
            </Button>
          </section>
          <section
            className="od-admin-panel od-ai-assist__panel"
            aria-labelledby="od-ai-doctor-title"
          >
            <h2 id="od-ai-doctor-title">Explain library issues</h2>
            <label className="od-admin-field">
              Game UUID (optional)
              <input
                className="od-admin-input"
                value={doctorUuid}
                onChange={(e) => setDoctorUuid(e.target.value)}
                placeholder="Game UUID"
              />
            </label>
            <label className="od-admin-field">
              Issue codes
              <input
                className="od-admin-input"
                value={issues}
                onChange={(e) => setIssues(e.target.value)}
                placeholder="missing_cover, path_mismatch"
              />
            </label>
            <Button disabled={disabled || !config.enabled} onClick={() => void doctorNotes()}>
              Explain issues
            </Button>
          </section>
          {output ? (
            <section className="od-admin-panel od-ai-assist__output" aria-label="AI Assist result">
              <h2>Result</h2>
              <pre>{output}</pre>
            </section>
          ) : null}
        </>
      ) : null}
    </Page>
  )
}
