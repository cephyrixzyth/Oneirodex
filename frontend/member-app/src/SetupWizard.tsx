import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Button, loadSetupState, submitSetupStep, type SetupState } from '@oneirodex/ui'
import { errorFromResponse } from '@oneirodex/ui'

const STEP_URLS: Record<number, string> = {
  1: '/setup',
  2: '/setup/smtp',
  3: '/setup/features',
  4: '/setup/igdb',
  5: '/setup/integrations',
  6: '/setup/library',
}
const STEP_TITLES: Record<number, string> = {
  1: 'Create administrator',
  2: 'Email delivery',
  3: 'Features',
  4: 'IGDB matching',
  5: 'Optional connections',
  6: 'First library',
}
const navigateWindow = (url: string) => window.location.assign(url)

function input(
  name: string,
  label: string,
  type = 'text',
  required = false,
  value = '',
): ReactNode {
  return (
    <label className="auth-pilot__field" key={name}>
      <span>{label}</span>
      <input
        name={name}
        type={type}
        defaultValue={value}
        autoComplete={type === 'password' ? 'new-password' : undefined}
        required={required}
      />
    </label>
  )
}

function checkbox(name: string, label: string, checked = true): ReactNode {
  return (
    <label className="auth-pilot__check" key={name}>
      <input name={name} type="checkbox" defaultChecked={checked} />
      <span>{label}</span>
    </label>
  )
}

function validationMessages(cause: unknown): string[] {
  const detail = (cause as { data?: { detail?: unknown } })?.data?.detail
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      const row = item as { loc?: unknown[]; msg?: unknown }
      return `${Array.isArray(row.loc) ? row.loc.slice(1).join('.') : 'Setup'}: ${String(row.msg || 'Invalid value')}`
    })
  }
  if (detail && typeof detail === 'object') {
    return Object.entries(detail as Record<string, unknown>).flatMap(([field, messages]) =>
      (Array.isArray(messages) ? messages : [messages]).map(
        (message) => `${field.replaceAll('_', ' ')}: ${String(message)}`,
      ),
    )
  }
  return []
}

export function SetupWizard({
  navigate = navigateWindow,
}: {
  navigate?: (url: string) => void
}): ReactNode {
  const [state, setState] = useState<SetupState | null>(null)
  const [error, setError] = useState('')
  const [details, setDetails] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    void loadSetupState()
      .then((result) => {
        setState(result)
        if (result.complete) navigate('/login')
        else if (result.step && STEP_URLS[result.step] !== window.location.pathname)
          navigate(STEP_URLS[result.step])
      })
      .catch(async (cause: unknown) => {
        if (controller.signal.aborted) return
        setError(cause instanceof Error ? cause.message : 'Setup could not be loaded.')
      })
    return () => controller.abort()
  }, [navigate])

  async function submit(event: FormEvent<HTMLFormElement>, skip = false) {
    event.preventDefault()
    if (!state?.step) return
    setError('')
    setDetails([])
    setBusy(true)
    const formData = new FormData(event.currentTarget)
    const values: Record<string, unknown> = { step: state.step, skip }
    for (const [key, value] of formData.entries()) values[key] = value
    for (const element of Array.from(event.currentTarget.elements)) {
      if (element instanceof HTMLInputElement && element.type === 'checkbox')
        values[element.name] = element.checked
    }
    try {
      const result = await submitSetupStep(values)
      if (result.complete) navigate(result.next_url || '/libraries')
      else if (result.next_url) navigate(result.next_url)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'This setup step could not be saved.')
      setDetails(validationMessages(cause))
    } finally {
      setBusy(false)
    }
  }

  if (error && !state)
    return (
      <section className="auth-pilot__message" role="alert">
        <p>{error}</p>
        <Button variant="primary" onClick={() => window.location.reload()}>
          Reload setup
        </Button>
      </section>
    )
  if (!state)
    return (
      <p className="auth-pilot__status" role="status">
        Loading setup…
      </p>
    )
  if (state.complete || !state.step)
    return (
      <p className="auth-pilot__status" role="status">
        Setup is already complete. Opening sign in…
      </p>
    )

  const step = state.step
  const settings = state.settings || {}
  const features = (settings.features || {}) as Record<string, boolean>
  const providerKeys = (settings.provider_keys || {}) as Record<string, boolean>
  const oidc = (settings.oidc || {}) as Record<string, string | boolean>

  return (
    <>
      <h1 className="auth-pilot__title">{STEP_TITLES[step] || 'Oneirodex setup'}</h1>
      <p className="auth-pilot__lede">
        {step === 3
          ? 'Step 3 of 6. Everything useful is on by default. Uncheck anything you do not want.'
          : `Step ${step} of 6. You can change these choices later in settings.`}
      </p>
      <form className="auth-pilot__form" onSubmit={(event) => void submit(event)}>
        {step === 1 ? (
          <>
            <p className="auth-pilot__message">
              Create the administrator account that will finish configuring this library.
            </p>
            {input('username', 'Administrator username', 'text', true)}
            {input('email', 'Administrator email', 'email', true)}
            {input('password', 'Password', 'password', true)}
            {input('confirm_password', 'Confirm password', 'password', true)}
          </>
        ) : null}
        {step === 2 ? (
          <>
            <p className="auth-pilot__message">
              Configure SMTP if this server should send invitation and account emails. Leave the
              password blank to keep the saved one.
            </p>
            {input('smtp_server', 'SMTP server', 'text', false, String(settings.smtp_server || ''))}
            {input('smtp_port', 'SMTP port', 'number', false, String(settings.smtp_port || 587))}
            {input(
              'smtp_username',
              'SMTP username',
              'text',
              false,
              String(settings.smtp_username || ''),
            )}
            {input(
              'smtp_password',
              settings.smtp_password_configured ? 'SMTP password (saved)' : 'SMTP password',
              'password',
            )}
            {input(
              'smtp_default_sender',
              'Default sender email',
              'email',
              false,
              String(settings.smtp_default_sender || ''),
            )}
            {checkbox('smtp_use_tls', 'Use TLS', Boolean(settings.smtp_use_tls))}
            {checkbox('smtp_enabled', 'Enable email delivery', Boolean(settings.smtp_enabled))}
          </>
        ) : null}
        {step === 3 ? (
          <>
            <h2 className="auth-pilot__section-title">Library</h2>
            <p className="auth-pilot__message">
              Authentication (OIDC/SSO) stays off — enable later under Admin → Integrations if needed.
            </p>
            {checkbox(
              'enable_game_updates',
              'Game updates',
              features.enable_game_updates !== false,
            )}
            {checkbox('enable_game_extras', 'Game extras', features.enable_game_extras !== false)}
            {checkbox(
              'attract_mode_enabled',
              'Attract mode',
              features.attract_mode_enabled !== false,
            )}
            {checkbox(
              'enable_arr_module',
              'Modules Arr / indexers',
              features.enable_arr_module !== false,
            )}
            {checkbox('enable_ai_assist', 'AI assist', features.enable_ai_assist !== false)}
            {checkbox(
              'enable_malware_scan',
              'Malware scanner',
              features.enable_malware_scan !== false,
            )}
            <p className="auth-pilot__message">
              Change anytime under Admin → Features. Compose/.env flags apply after restart.
            </p>
          </>
        ) : null}
        {step === 4 ? (
          <>
            <p className="auth-pilot__message">
              IGDB credentials improve title matching. You can skip this and add them later.
            </p>
            {input(
              'igdb_client_id',
              'IGDB client ID',
              'text',
              true,
              String(settings.igdb_client_id || ''),
            )}
            {input(
              'igdb_client_secret',
              settings.igdb_secret_configured ? 'IGDB client secret (saved)' : 'IGDB client secret',
              'password',
              true,
            )}
          </>
        ) : null}
        {step === 5 ? (
          <>
            <p className="auth-pilot__message">
              Optional provider credentials are stored on this server. Blank values keep existing
              credentials. OIDC stays disabled until an administrator turns it on.
            </p>
            {(
              [
                'steam_web_api_key',
                'steamgriddb_api_key',
                'giantbomb_api_key',
                'mobygames_api_key',
                'thegamesdb_api_key',
              ] as const
            ).map((key) =>
              input(
                key,
                `${key.replaceAll('_', ' ')}${providerKeys[key] ? ' (saved)' : ''}`,
                'password',
              ),
            )}
            {checkbox(
              'enable_hltb_integration',
              'Enable HowLongToBeat data',
              Boolean(settings.enable_hltb_integration),
            )}
            {checkbox('configure_oidc', 'Configure OIDC fields (provider remains disabled)', false)}
            {input(
              'oidc_issuer_url',
              `OIDC issuer URL${oidc.secret_configured ? ' (secret saved)' : ''}`,
              'text',
              false,
              String(oidc.issuer_url || ''),
            )}
            {input('oidc_client_id', 'OIDC client ID', 'text', false, String(oidc.client_id || ''))}
            {input('oidc_client_secret', 'OIDC client secret', 'password')}
            {input(
              'oidc_redirect_uri',
              'OIDC redirect URI',
              'text',
              false,
              String(oidc.redirect_uri || ''),
            )}
            {input(
              'oidc_scopes',
              'OIDC scopes',
              'text',
              false,
              String(oidc.scopes || 'openid email profile'),
            )}
            {input(
              'oidc_role_claim',
              'OIDC role claim',
              'text',
              false,
              String(oidc.role_claim || ''),
            )}
          </>
        ) : null}
        {step === 6 ? (
          <>
            <p className="auth-pilot__message">
              Add the first library now or finish setup and add it later. The server path must exist
              inside an allowed library location.
            </p>
            {input('library_name', 'Library name')}
            <label className="auth-pilot__field">
              <span>Platform</span>
              <select className="od-select" name="platform" defaultValue="" required>
                <option value="" disabled>
                  Choose a platform
                </option>
                {state.platforms.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.label}
                  </option>
                ))}
              </select>
            </label>
            {input('folder_path', 'Server folder path')}
            <label className="auth-pilot__field">
              <span>Folder layout</span>
              <select className="od-select" name="scan_mode">
                <option value="folders">Games are in folders</option>
                <option value="files">Game files are in one folder</option>
              </select>
            </label>
            <label className="auth-pilot__field">
              <span>Scan depth</span>
              <select className="od-select" name="scan_depth">
                <option value="1">One folder deep</option>
                <option value="2">Two folders deep</option>
              </select>
            </label>
          </>
        ) : null}
        {error ? (
          <div className="auth-pilot__error" role="alert">
            <p>{error}</p>
            {details.length ? (
              <ul>
                {details.map((message) => (
                  <li key={message}>{message}</li>
                ))}
              </ul>
            ) : null}
          </div>
        ) : null}
        <Button variant="primary" className="auth-pilot__submit" disabled={busy} type="submit">
          {busy ? 'Saving…' : step === 6 ? 'Finish setup' : 'Continue'}
        </Button>
        {[2, 4, 5, 6].includes(step) ? (
          <Button
            variant="secondary"
            className="auth-pilot__submit"
            disabled={busy}
            onClick={(event) => {
              const form = event.currentTarget.form
              if (form)
                void submit(
                  { preventDefault() {}, currentTarget: form } as FormEvent<HTMLFormElement>,
                  true,
                )
            }}
          >
            {step === 6 ? 'Finish without a library' : 'Skip this step'}
          </Button>
        ) : null}
      </form>
    </>
  )
}
