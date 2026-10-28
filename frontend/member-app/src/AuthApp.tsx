import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import {
  registerAccount,
  requestPasswordReset,
  resetPassword,
  confirmEmail,
  signIn,
  setCsrfToken,
  Button,
  type RegistrationResult,
  errorFromResponse,
} from '@oneirodex/ui'
import { AuthServerNotices } from './AuthServerNotices'
import { SetupWizard } from './SetupWizard'

interface RuntimeBootstrap {
  csrf_token: string
  oidc_enabled: boolean
  oidc_display_name: string
}

type Page = 'login' | 'register' | 'reset-request' | 'reset-confirm' | 'confirm-email' | 'setup'
type ConfirmationState =
  'loading' | 'ready' | 'confirmed' | 'already' | 'expired' | 'invalid' | 'not-found' | 'error'
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
  const passwordResetRequested = params.get('password_reset_requested') === '1'
  const inviteToken = params.get('token') || undefined
  const [bootstrap, setBootstrap] = useState<RuntimeBootstrap | null>(null)
  const [bootError, setBootError] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [registered, setRegistered] = useState<RegistrationResult | null>(null)
  const [confirmationState, setConfirmationState] = useState<ConfirmationState>('loading')

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
      setNotice('Your password has been reset.')
    } else if (page === 'login' && passwordResetRequested) {
      setNotice('If that email is registered, password reset instructions were sent.')
    }
  }, [page, passwordReset, passwordResetRequested])

  useEffect(() => {
    if (!bootstrap || page !== 'confirm-email') return
    const controller = new AbortController()
    setConfirmationState('loading')
    setError('')
    setNotice('')
    void fetch(`/api/auth/confirm/${encodeURIComponent(token)}`, {
      credentials: 'same-origin',
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw await errorFromResponse(response, 'Confirm email')
        const result = (await response.json()) as { already_confirmed?: boolean }
        setConfirmationState(result.already_confirmed ? 'already' : 'ready')
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        const message = cause instanceof Error ? cause.message : 'Could not confirm this email.'
        const normalized = message.toLowerCase()
        setConfirmationState(
          normalized.includes('expired')
            ? 'expired'
            : normalized.includes('not found')
              ? 'not-found'
              : normalized.includes('invalid') || normalized.includes('not valid')
                ? 'invalid'
                : 'error',
        )
        if (
          !normalized.includes('expired') &&
          !normalized.includes('not found') &&
          !normalized.includes('invalid') &&
          !normalized.includes('not valid')
        ) {
          setError(message)
        }
      })
    return () => controller.abort()
  }, [bootstrap, page, token])

  async function submit(
    event: FormEvent<HTMLFormElement>,
    action: (data: FormData) => Promise<void>,
    clearOnError = false,
  ) {
    event.preventDefault()
    const form = event.currentTarget
    setError('')
    setNotice('')
    setBusy(true)
    try {
      await action(new FormData(event.currentTarget))
    } catch (cause) {
      if (clearOnError) form.reset()
      setError(cause instanceof Error ? cause.message : 'The request could not be completed.')
    } finally {
      setBusy(false)
    }
  }

  const confirmationError =
    page === 'confirm-email' &&
    ['expired', 'invalid', 'not-found', 'error'].includes(confirmationState)

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
          className="auth-pilot__form auth-pilot__form--login"
          noValidate
          onSubmit={(event) => {
            const form = event.currentTarget
            const data = new FormData(form)
            const username = String(data.get('username') || '')
            const password = String(data.get('password') || '')
            const missingUsername = !username.trim()
            const missingPassword = !password.trim()
            if (missingUsername || missingPassword) {
              event.preventDefault()
              setNotice('')
              setError(
                missingUsername && missingPassword
                  ? 'Please enter your username and password.'
                  : missingUsername
                    ? 'Please enter your username.'
                    : 'Please enter your password.',
              )
              return
            }
            void submit(
              event,
              async (formData) => {
                const result = await signIn(
                  {
                    username: String(formData.get('username') || ''),
                    password: String(formData.get('password') || ''),
                  },
                  { next: params.get('next') || undefined },
                )
                navigate(result.next_url)
              },
              true,
            )
          }}
        >
          <label className="auth-pilot__field">
            <span>Username</span>
            <input autoComplete="username" name="username" required />
          </label>
          <label className="auth-pilot__field">
            <span>Password</span>
            <input autoComplete="current-password" name="password" type="password" required />
          </label>
          <Button
            variant="primary"
            size="lg"
            className="auth-pilot__submit"
            disabled={busy}
            type="submit"
          >
            {busy ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>
        <nav className="auth-pilot__links auth-pilot__links--login" aria-label="Account actions">
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
              ? "You were invited to join this Oneirodex library. Choose a username and password to request an account. After confirming your email, you will choose the password used to sign in. You will not share the inviter's login."
              : 'Registration requires a whitelisted email or a valid invite link.'}
          </p>
          <form
            className="auth-pilot__form auth-pilot__form--register"
            noValidate
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
            <Button
              variant="primary"
              size="lg"
              className="auth-pilot__submit"
              disabled={busy}
              type="submit"
            >
              {busy ? 'Registering…' : 'Register'}
            </Button>
          </form>
          <nav
            className="auth-pilot__links auth-pilot__links--register"
            aria-label="Account actions"
          >
            <a href="/login">Back to sign in</a>
          </nav>
        </>
      )
    ) : page === 'reset-request' ? (
      <>
        <h1 className="auth-pilot__title">Reset password</h1>
        <p className="auth-pilot__lede">
          Enter your email and we will send a reset link if an account exists.
        </p>
        <form
          className="auth-pilot__form auth-pilot__form--account"
          noValidate
          onSubmit={(event) =>
            submit(event, async (data) => {
              await requestPasswordReset(String(data.get('email') || ''))
              navigate('/login?password_reset_requested=1')
            })
          }
        >
          <label className="auth-pilot__field">
            <span>Email</span>
            <input
              autoComplete="email"
              name="email"
              placeholder="you@example.com"
              type="email"
              required
            />
          </label>
          <Button
            variant="primary"
            size="lg"
            className="auth-pilot__submit auth-pilot__submit--account"
            disabled={busy}
            type="submit"
          >
            {busy ? 'Sending…' : 'Send reset link'}
          </Button>
        </form>
        <nav className="auth-pilot__links auth-pilot__links--account" aria-label="Account actions">
          <a href="/login">Back to sign in</a>
        </nav>
      </>
    ) : page === 'reset-confirm' ? (
      <>
        <h1 className="auth-pilot__title">Choose a new password</h1>
        <p className="auth-pilot__lede">Enter and confirm your new password to finish the reset.</p>
        <form
          className="auth-pilot__form auth-pilot__form--account"
          noValidate
          onSubmit={(event) =>
            submit(event, async (data) => {
              const result = await resetPassword(token, {
                password: String(data.get('password') || ''),
                confirm_password: String(data.get('confirm_password') || ''),
              })
              navigate(
                result.next_url === '/login'
                  ? '/login?password_reset=1'
                  : result.next_url || '/login?password_reset=1',
              )
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
          <Button
            variant="primary"
            size="lg"
            className="auth-pilot__submit auth-pilot__submit--account"
            disabled={busy}
            type="submit"
          >
            {busy ? 'Saving…' : 'Reset password'}
          </Button>
        </form>
        <nav className="auth-pilot__links auth-pilot__links--account" aria-label="Account actions">
          <a href="/login">Back to sign in</a>
        </nav>
      </>
    ) : (
      <>
        <h1 className="auth-pilot__title">
          {confirmationState === 'confirmed'
            ? 'Account activated'
            : confirmationState === 'already'
              ? 'Already confirmed'
              : confirmationState === 'expired'
                ? 'Link expired'
                : confirmationState === 'invalid'
                  ? 'Invalid link'
                  : confirmationState === 'not-found'
                    ? 'Account not found'
                    : confirmationState === 'error'
                      ? 'Could not confirm this email'
                      : 'Confirm your email'}
        </h1>
        <p
          className="auth-pilot__lede"
          role={
            ['expired', 'invalid', 'not-found'].includes(confirmationState) ? 'alert' : undefined
          }
        >
          {confirmationState === 'confirmed'
            ? 'Your email is confirmed. Sign in to open your household library.'
            : confirmationState === 'already'
              ? 'Your account is already activated. You can sign in and continue.'
              : confirmationState === 'expired'
                ? 'Request a new activation from an admin or try registering again with a fresh invite.'
                : confirmationState === 'invalid'
                  ? 'This confirmation link is not valid. Check your email for the correct link, or sign in if your account is already active.'
                  : confirmationState === 'not-found'
                    ? 'The account for this confirmation link was not found.'
                    : confirmationState === 'error'
                      ? 'Please try again or return to sign in.'
                      : confirmationState === 'ready'
                        ? 'To protect your account, choose the password that will be used to sign in. This confirms that you control this email address.'
                        : 'We’re checking your confirmation link.'}
        </p>
        {confirmationState === 'ready' ? (
          <form
            className="auth-pilot__form auth-pilot__form--account"
            noValidate
            onSubmit={(event) => {
              const form = event.currentTarget
              const data = new FormData(form)
              const password = String(data.get('password') || '')
              const confirmPassword = String(data.get('confirm_password') || '')
              if (password.length < 8) {
                event.preventDefault()
                setError('Password must be at least 8 characters.')
                return
              }
              if (password !== confirmPassword) {
                event.preventDefault()
                setError('Passwords do not match.')
                return
              }
              void submit(event, async (formData) => {
                await confirmEmail(token, {
                  password: String(formData.get('password') || ''),
                  confirm_password: String(formData.get('confirm_password') || ''),
                })
                setConfirmationState('confirmed')
                setNotice('Your email is confirmed. Sign in to open your household library.')
              })
            }}
          >
            <label className="auth-pilot__field">
              <span>Choose a password</span>
              <input
                autoComplete="new-password"
                minLength={8}
                name="password"
                type="password"
                required
              />
            </label>
            <label className="auth-pilot__field">
              <span>Confirm password</span>
              <input
                autoComplete="new-password"
                minLength={8}
                name="confirm_password"
                type="password"
                required
              />
            </label>
            <Button
              variant="primary"
              size="lg"
              className="auth-pilot__submit auth-pilot__submit--account"
              disabled={busy}
              type="submit"
            >
              {busy ? 'Confirming…' : 'Confirm email and activate account'}
            </Button>
          </form>
        ) : null}
        <nav
          className={
            confirmationError
              ? 'auth-pilot__links auth-pilot__links--account auth-pilot__links--confirmation-error'
              : 'auth-pilot__links auth-pilot__links--account'
          }
          aria-label="Account actions"
        >
          <a
            className={
              confirmationError
                ? 'od-btn od-btn--primary od-btn--lg auth-pilot__confirmation-back'
                : undefined
            }
            href="/login"
          >
            Back to sign in
          </a>
          {!confirmationError ? <a href="/register">Create account</a> : null}
        </nav>
      </>
    )

  return (
    <main className="auth-pilot">
      <a className="auth-pilot__skip" href="#auth-content">
        Skip to account form
      </a>
      <section
        className={
          page === 'login'
            ? 'auth-pilot__card auth-pilot__card--login'
            : page === 'register'
              ? 'auth-pilot__card auth-pilot__card--register'
              : page === 'reset-request' || page === 'reset-confirm'
                ? 'auth-pilot__card auth-pilot__card--account'
                : page === 'confirm-email'
                  ? `auth-pilot__card auth-pilot__card--account${confirmationError ? ' auth-pilot__card--confirmation-error' : ''}`
                  : 'auth-pilot__card'
        }
        id="auth-content"
        aria-labelledby="auth-brand"
      >
        <a className="auth-pilot__brand" href="/" id="auth-brand" aria-label="Oneirodex">
          <img
            className="auth-pilot__brand-mark"
            src="/static/newstyle/oneirodex_mark.svg"
            alt=""
            width="56"
            height="56"
          />
        </a>
        {content}
        <AuthServerNotices />
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
