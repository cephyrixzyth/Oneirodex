import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import {
  registerAccount,
  requestPasswordReset,
  resetPassword,
  signIn,
  setCsrfToken,
  Button,
  type RegistrationResult,
  errorFromResponse,
} from '@oneirodex/ui'
import { SetupWizard } from './SetupWizard'

interface RuntimeBootstrap {
  csrf_token: string
  oidc_enabled: boolean
  oidc_display_name: string
}

type Page = 'login' | 'register' | 'reset-request' | 'reset-confirm' | 'confirm-email' | 'setup'
const navigateWindow = (url: string) => window.location.assign(url)

function pageForPath(path: string): Page {
  if (path === '/setup' || path.startsWith('/setup/')) return 'setup'
  if (path === '/register') return 'register'
  if (path === '/reset_password_request') return 'reset-request'
  if (path.startsWith('/reset_password/')) return 'reset-confirm'
  if (path.startsWith('/confirm/')) return 'confirm-email'
  return 'login'
}

function tokenForPath(path: string): string {
  const parts = path.split('/').filter(Boolean)
  if (parts.length <= 1) return ''
  try {
    return decodeURIComponent(parts[1])
  } catch {
    return ''
  }
}

async function loadBootstrap(): Promise<RuntimeBootstrap> {
  const response = await fetch('/api/auth/runtime-bootstrap', { credentials: 'same-origin' })
  if (!response.ok) throw await errorFromResponse(response, 'Load account page')
  const payload = (await response.json()) as RuntimeBootstrap
  setCsrfToken(payload.csrf_token)
  return payload
}

export function AuthApp({
  navigate = navigateWindow,
}: {
  navigate?: (url: string) => void
}): ReactNode {
  const page = pageForPath(window.location.pathname)
  const token = tokenForPath(window.location.pathname)
  const params = new URLSearchParams(window.location.search)
  const passwordReset = params.get('password_reset') === '1'
  const inviteToken = params.get('token') || undefined
  const [bootstrap, setBootstrap] = useState<RuntimeBootstrap | null>(null)
  const [bootError, setBootError] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [registered, setRegistered] = useState<RegistrationResult | null>(null)

  const load = () => {
    setBootError('')
    void loadBootstrap()
      .then(setBootstrap)
      .catch((cause: unknown) => {
        setBootError(cause instanceof Error ? cause.message : 'Could not load this page.')
      })
  }

  useEffect(() => load(), [])

  useEffect(() => {
    if (page === 'login' && passwordReset) {
      setNotice('Your password has been reset. Sign in with your new password.')
    }
  }, [page, passwordReset])

  useEffect(() => {
    if (!bootstrap || page !== 'confirm-email') return
    const controller = new AbortController()
    void fetch(`/api/auth/confirm/${encodeURIComponent(token)}`, {
      credentials: 'same-origin',
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw await errorFromResponse(response, 'Confirm email')
        const result = (await response.json()) as { already_confirmed?: boolean }
        setNotice(
          result.already_confirmed
            ? 'This email is already confirmed.'
            : 'Your email is confirmed. You can sign in now.',
        )
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted)
          setError(cause instanceof Error ? cause.message : 'Could not confirm this email.')
      })
    return () => controller.abort()
  }, [bootstrap, page, token])

  async function submit(
    event: FormEvent<HTMLFormElement>,
    action: (data: FormData) => Promise<void>,
  ) {
    event.preventDefault()
    setError('')
    setNotice('')
    setBusy(true)
    try {
      await action(new FormData(event.currentTarget))
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The request could not be completed.')
    } finally {
      setBusy(false)
    }
  }

  const content =
    !bootstrap && !bootError ? (
      <p className="auth-pilot__status" role="status">
        Loading account page…
      </p>
    ) : bootError ? (
      <section className="auth-pilot__message" role="alert">
        <p>{bootError}</p>
        <Button variant="primary" onClick={load}>
          Try again
        </Button>
      </section>
    ) : page === 'setup' ? (
      <SetupWizard navigate={navigate} />
    ) : page === 'login' ? (
      <>
        <h1 className="auth-pilot__title">Sign in to Oneirodex</h1>
        <p className="auth-pilot__lede">Household library access for your gaming sphere.</p>
        <form
          className="auth-pilot__form"
          onSubmit={(event) =>
            submit(event, async (data) => {
              const result = await signIn(
                {
                  username: String(data.get('username') || ''),
                  password: String(data.get('password') || ''),
                },
                { next: params.get('next') || undefined },
              )
              navigate(result.next_url)
            })
          }
        >
          <label className="auth-pilot__field">
            <span>Username</span>
            <input autoComplete="username" name="username" required />
          </label>
          <label className="auth-pilot__field">
            <span>Password</span>
            <input autoComplete="current-password" name="password" type="password" required />
          </label>
          <Button variant="primary" className="auth-pilot__submit" disabled={busy} type="submit">
            {busy ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>
        <nav className="auth-pilot__links" aria-label="Account actions">
          <a href="/register">Create account</a>
          <a href="/reset_password_request">Forgot password?</a>
          {bootstrap?.oidc_enabled ? <a href="/login/oidc">{bootstrap.oidc_display_name}</a> : null}
        </nav>
      </>
    ) : page === 'register' ? (
      registered ? (
        <>
          <h1 className="auth-pilot__title">Request received</h1>
          <p className="auth-pilot__message" role="status">
            {registered.message ||
              'If the details can be used to create an account, check your email for next steps.'}
          </p>
          <a className="od-btn od-btn--primary" href={registered.next_url}>
            Back to sign in
          </a>
        </>
      ) : (
        <>
          <h1 className="auth-pilot__title">Create your account</h1>
          <p className="auth-pilot__lede">
            {inviteToken
              ? 'You were invited to join this Oneirodex library. Create your own account.'
              : 'Registration requires a whitelisted email or a valid invite link.'}
          </p>
          <form
            className="auth-pilot__form"
            onSubmit={(event) =>
              submit(event, async (data) => {
                setRegistered(
                  await registerAccount(
                    {
                      username: String(data.get('username') || ''),
                      email: String(data.get('email') || ''),
                      password: String(data.get('password') || ''),
                    },
                    { inviteToken },
                  ),
                )
              })
            }
          >
            <label className="auth-pilot__field">
              <span>Username</span>
              <input
                autoComplete="username"
                name="username"
                minLength={3}
                maxLength={64}
                required
              />
            </label>
            <label className="auth-pilot__field">
              <span>Email</span>
              <input autoComplete="email" name="email" type="email" required />
            </label>
            <label className="auth-pilot__field">
              <span>Password</span>
              <input
                autoComplete="new-password"
                name="password"
                type="password"
                minLength={8}
                required
              />
            </label>
            <Button variant="primary" className="auth-pilot__submit" disabled={busy} type="submit">
              {busy ? 'Creating account…' : 'Create account'}
            </Button>
          </form>
          <nav className="auth-pilot__links" aria-label="Account actions">
            <a href="/login">Back to sign in</a>
          </nav>
        </>
      )
    ) : page === 'reset-request' ? (
      <>
        <h1 className="auth-pilot__title">Reset your password</h1>
        <p className="auth-pilot__lede">
          Enter your account email. If it is registered, we’ll send reset instructions.
        </p>
        <form
          className="auth-pilot__form"
          onSubmit={(event) =>
            submit(event, async (data) => {
              const result = await requestPasswordReset(String(data.get('email') || ''))
              setNotice(
                result.message ||
                  'If that email is registered, password reset instructions were sent.',
              )
            })
          }
        >
          <label className="auth-pilot__field">
            <span>Email</span>
            <input autoComplete="email" name="email" type="email" required />
          </label>
          <Button variant="primary" className="auth-pilot__submit" disabled={busy} type="submit">
            {busy ? 'Sending…' : 'Send reset instructions'}
          </Button>
        </form>
        <nav className="auth-pilot__links" aria-label="Account actions">
          <a href="/login">Back to sign in</a>
        </nav>
      </>
    ) : page === 'reset-confirm' ? (
      <>
        <h1 className="auth-pilot__title">Choose a new password</h1>
        <form
          className="auth-pilot__form"
          onSubmit={(event) =>
            submit(event, async (data) => {
              const result = await resetPassword(token, {
                password: String(data.get('password') || ''),
                confirm_password: String(data.get('confirm_password') || ''),
              })
              navigate(result.next_url || '/login?password_reset=1')
            })
          }
        >
          <label className="auth-pilot__field">
            <span>New password</span>
            <input
              autoComplete="new-password"
              name="password"
              type="password"
              minLength={8}
              required
            />
          </label>
          <label className="auth-pilot__field">
            <span>Confirm password</span>
            <input
              autoComplete="new-password"
              name="confirm_password"
              type="password"
              minLength={8}
              required
            />
          </label>
          <Button variant="primary" className="auth-pilot__submit" disabled={busy} type="submit">
            {busy ? 'Saving…' : 'Save new password'}
          </Button>
        </form>
        <nav className="auth-pilot__links" aria-label="Account actions">
          <a href="/login">Back to sign in</a>
        </nav>
      </>
    ) : (
      <>
        <h1 className="auth-pilot__title">Confirm your email</h1>
        <p className="auth-pilot__lede">We’re checking your confirmation link.</p>
        <nav className="auth-pilot__links" aria-label="Account actions">
          <a href="/login">Back to sign in</a>
          <a href="/register">Create account</a>
        </nav>
      </>
    )

  return (
    <main className="auth-pilot">
      <a className="auth-pilot__skip" href="#auth-content">
        Skip to account form
      </a>
      <section className="auth-pilot__card" id="auth-content" aria-labelledby="auth-brand">
        <a className="auth-pilot__brand" href="/" id="auth-brand">
          Oneirodex
        </a>
        {content}
        {error ? (
          <p className="auth-pilot__error" role="alert">
            {error}
          </p>
        ) : null}
        {notice ? (
          <p className="auth-pilot__notice" role="status">
            {notice}
          </p>
        ) : null}
      </section>
    </main>
  )
}
