import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Button, PageStatus, DataTable } from '@oneirodex/ui'
import { Page } from '../components/Page'
import { getJson, putJson, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { AmbientLightingPanel } from '../components/AmbientLightingPanel'

const API = '/api/admin/features/settings'
const FIELDS = [
  ['enable_game_updates', 'Game updates folders'],
  ['enable_game_extras', 'Game extras folders'],
  ['attract_mode_enabled', 'Attract mode'],
  ['enable_arr_module', 'Arr module preference'],
  ['enable_ai_assist', 'AI assist preference'],
  ['enable_malware_scan', 'Malware scanner preference'],
  ['allow_children_in_household_lobby', 'Let child accounts join the household voice lobby'],
] as const
type Preferences = Record<(typeof FIELDS)[number][0], boolean>
type Solver = { enabled: boolean; url: string; provider: string; max_tier: number }
function solverDraft(config: any): Solver {
  if (
    !config ||
    typeof config.db_enabled !== 'boolean' ||
    typeof config.url !== 'string' ||
    typeof config.max_tier !== 'number'
  )
    throw new Error('Solver settings returned an invalid response.')
  return {
    enabled: config.db_enabled,
    url: config.url,
    provider: config.provider,
    max_tier: config.max_tier,
  }
}
function preferences(data: any): Preferences {
  if (!data || FIELDS.some(([key]) => typeof data[key] !== 'boolean'))
    throw new Error('Feature settings returned an invalid response.')
  return data
}
export function FeaturesPage() {
  const [draft, setDraft] = useState<Preferences | null>(null)
  const [process, setProcess] = useState<any[]>([])
  const [scanner, setScanner] = useState<any>(null)
  const [solver, setSolver] = useState<Solver | null>(null)
  const [savedSolver, setSavedSolver] = useState<Solver | null>(null)
  const [effectiveSolver, setEffectiveSolver] = useState(false)
  const [envSolver, setEnvSolver] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [reload, setReload] = useState(0)
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadFailed(false)
    setError('')
    getJson(API)
      .then((data) => {
        if (cancelled) return
        const prefs = preferences(data.preferences)
        const challenge = solverDraft(data.challenge)
        if (!Array.isArray(data.process) || !data.scanner?.clamav || !data.scanner?.heuristics)
          throw new Error('Feature status returned an invalid response.')
        setDraft(prefs)
        setProcess(data.process)
        setScanner(data.scanner)
        setSolver(challenge)
        setSavedSolver(challenge)
        setEffectiveSolver(Boolean(data.challenge.enabled))
        setEnvSolver(Boolean(data.challenge.env_enabled))
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
  async function action(work: () => Promise<void>) {
    if (loading || loadFailed || pending.current) return
    pending.current = true
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await work()
    } catch (err) {
      setError(errorText(err) || 'Could not complete the action.')
    } finally {
      pending.current = false
      setBusy(false)
    }
  }
  function save(event: FormEvent) {
    event.preventDefault()
    void action(async () => {
      const data = await putJson(API, draft)
      setDraft(preferences(data.preferences))
      setMessage('Feature preferences saved.')
    })
  }
  function saveSolver(event: FormEvent) {
    event.preventDefault()
    void action(async () => {
      const data = await putJson('/api/admin/features/challenge', solver)
      const accepted = solverDraft(data.challenge)
      setSolver(accepted)
      setSavedSolver(accepted)
      setEffectiveSolver(Boolean(data.challenge.enabled))
      setEnvSolver(Boolean(data.challenge.env_enabled))
      setMessage('Solver settings saved. Use Test solver to check the connection.')
    })
  }
  const dirtySolver = JSON.stringify(solver) !== JSON.stringify(savedSolver)
  const disabled = loading || loadFailed || busy
  return (
    <Page
      title="Features"
      lede="Choose household preferences and review which product modules are available."
    >
      <PageStatus
        loading={loading}
        loadingMessage="Loading feature settings…"
        error={error || null}
      />
      {loadFailed ? (
        <Button onClick={() => setReload((value) => value + 1)}>Retry loading settings</Button>
      ) : null}
      {message ? (
        <PageStatus announcement="status" className="od-admin-hint">
          {message}
        </PageStatus>
      ) : null}
      {draft ? (
        <form className="od-admin-panel" onSubmit={save}>
          <fieldset className="od-admin-fieldset" disabled={disabled}>
            <legend>Household preferences</legend>
            {FIELDS.map(([key, label]) => (
              <label key={key} className="od-admin-field">
                <input
                  type="checkbox"
                  checked={draft[key]}
                  onChange={(event) => {
                    setDraft({ ...draft, [key]: event.target.checked })
                    setMessage('')
                  }}
                />{' '}
                {label}
              </label>
            ))}
            <p className="od-admin-hint">
              Process settings may override module preferences. Child accounts stay out of the
              household lobby unless explicitly allowed; adult and administrator rooms remain closed
              to children.
            </p>
          </fieldset>
          <Button type="submit" variant="primary" disabled={disabled}>
            Save preferences
          </Button>
        </form>
      ) : null}
      {process.length ? (
        <section className="od-admin-panel" aria-labelledby="feature-process-title">
          <h2 id="feature-process-title">Process settings</h2>
          <p className="od-admin-hint">
            These settings are read-only here. Update the deployment environment and restart to
            change them. Authentication and safety-sensitive features require explicit
            configuration.
          </p>
          <DataTable
            caption="Product module availability"
            scrollLabel="Process feature settings table"
            rows={process}
            getRowKey={(row) => row.key}
            columns={[
              {
                key: 'label',
                label: 'Module',
                render: (row) => (
                  <>
                    {row.label}
                    {row.opt_in ? ' (opt-in)' : ''}
                    {row.help ? <p className="od-admin-hint">{row.help}</p> : null}
                  </>
                ),
              },
              { key: 'key', label: 'Process flag', render: (row) => <code>{row.key}</code> },
              { key: 'on', label: 'State', render: (row) => (row.on ? 'On' : 'Off') },
            ]}
          />
        </section>
      ) : null}
      <AmbientLightingPanel />
      {solver ? (
        <form className="od-admin-panel" onSubmit={saveSolver}>
          <fieldset className="od-admin-fieldset" disabled={disabled}>
            <legend>Challenge solver</legend>
            <p className="od-admin-hint">
              Optional sidecar for indexers that return browser challenges. Keep solver ports
              private. Saving does not contact the solver; testing uses the saved connection.
            </p>
            <label className="od-admin-field">
              <input
                type="checkbox"
                checked={solver.enabled}
                onChange={(event) => {
                  setSolver({ ...solver, enabled: event.target.checked })
                  setMessage('')
                }}
              />{' '}
              Enable challenge solver preference
            </label>
            <label className="od-admin-field">
              Solver URL
              <input
                className="od-admin-input"
                type="url"
                maxLength={2048}
                value={solver.url}
                onChange={(event) => setSolver({ ...solver, url: event.target.value })}
              />
            </label>
            <label className="od-admin-field">
              Solver provider
              <select
                className="od-admin-input"
                aria-label="Solver provider"
                value={solver.provider}
                onChange={(event) => setSolver({ ...solver, provider: event.target.value })}
              >
                <option value="flaresolverr_compat">FlareSolverr compatible</option>
                <option value="trawl">TRAWL</option>
                <option value="token_api">Token API</option>
              </select>
            </label>
            <label className="od-admin-field">
              Maximum solver tier
              <input
                className="od-admin-input"
                type="number"
                required
                min={1}
                step={1}
                value={solver.max_tier}
                onChange={(event) => setSolver({ ...solver, max_tier: Number(event.target.value) })}
              />
            </label>
            <p className="od-admin-hint">
              Effective state: {effectiveSolver ? 'Enabled' : 'Disabled'}. Process override:{' '}
              {envSolver ? 'On' : 'Off'}. Save changes before testing.
            </p>
          </fieldset>
          <div className="od-admin-actions-row">
            <Button type="submit" variant="primary" disabled={disabled}>
              Save solver settings
            </Button>
            <Button
              disabled={disabled || dirtySolver || !effectiveSolver || !savedSolver?.url}
              onClick={() =>
                void action(async () => {
                  const data = await postJson('/api/admin/features/challenge/test')
                  if (data.result?.probe_ok) setMessage('Solver connection successful.')
                  else
                    setError(
                      data.result?.error ||
                        'Solver test failed. Check the saved connection settings.',
                    )
                })
              }
            >
              Test solver
            </Button>
          </div>
        </form>
      ) : null}
      {scanner ? (
        <section className="od-admin-panel" aria-labelledby="feature-scanner-title">
          <h2 id="feature-scanner-title">Malware scanner</h2>
          <dl>
            <dt>Module</dt>
            <dd>{scanner.enabled ? 'Enabled' : 'Disabled'}</dd>
            <dt>Block on hit</dt>
            <dd>{scanner.block_on_hit ? 'On' : 'Off'}</dd>
            <dt>Filename heuristics</dt>
            <dd>
              {scanner.heuristics.enabled ? 'Enabled' : 'Disabled'}; block on match:{' '}
              {scanner.heuristics.block_on_match ? 'On' : 'Off'}
            </dd>
            <dt>ClamAV</dt>
            <dd>
              {scanner.clamav.reachable
                ? `Reachable ${scanner.clamav.version || ''}`
                : 'Unavailable'}
            </dd>
            <dt>Connection</dt>
            <dd>
              {scanner.settings.socket_configured
                ? 'Local socket configured'
                : `${scanner.settings.host || 'Not configured'}:${scanner.settings.port || ''}`}
            </dd>
          </dl>
          {scanner.clamav.error ? <p className="od-admin-hint">{scanner.clamav.error}</p> : null}
          <p className="od-admin-hint">
            Filename heuristics do not establish malware certainty. ClamAV provides signature scans.
            Blocking skips files or folders when a heuristic warns or ClamAV finds a hit.
          </p>
        </section>
      ) : null}
    </Page>
  )
}
