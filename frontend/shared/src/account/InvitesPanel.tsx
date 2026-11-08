import { useCallback, useEffect, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { createInvite, listInvites, revokeInvite } from '../accountApi.js'
import type { ListInvitesResponse } from '../accountApi.js'
import { confirmAction } from '../confirmDialog.js'
import { copyText } from '../copyText.js'
import { PageStatus } from '../pageStatus.js'
import { formatWhen, messageOf } from './accountModalShared'
import { Note } from './AccountPanels'

/* InvitesPanel moved out of AccountModal (v11 cycle, H-D.2) — unchanged. */

export function InvitesPanel(): ReactNode {
  const [state, setState] = useState<ListInvitesResponse | null>(null)
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState('')

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      setState(await listInvites({ signal }))
    } catch (err) {
      if (signal?.aborted) return
      setError(messageOf(err, 'Could not load your invites.'))
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    load(controller.signal)
    return () => controller.abort()
  }, [load])

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    setDone('')
    try {
      const data = await createInvite(email.trim() ? { email: email.trim() } : {})
      setEmail('')
      setDone(
        data.emailed
          ? 'Invite created and emailed.'
          : 'Invite created. Copy the link below and pass it on.',
      )
      await load()
    } catch (err) {
      setError(messageOf(err, 'Could not create the invite.'))
    } finally {
      setBusy(false)
    }
  }

  async function handleRevoke(token: string) {
    setError('')
    setDone('')
    const confirmed = await confirmAction({
      title: 'Delete this invite?',
      body: 'Anyone with this invite link will no longer be able to use it.',
      confirmLabel: 'Delete invite',
      cancelLabel: 'Keep invite',
    })
    if (!confirmed) return
    try {
      await revokeInvite(token)
      await load()
    } catch (err) {
      setError(messageOf(err, 'Could not revoke that invite.'))
    }
  }

  if (!state) {
    return (
      <>
        <Note tone="error">{error}</Note>
        {error ? null : <PageStatus loading inline className="od-acct__empty" />}
      </>
    )
  }

  return (
    <>
      <Note tone="error">{error}</Note>
      <Note tone="good">{done}</Note>
      {!state.smtp_enabled ? (
        <Note tone="warning">
          SMTP is not configured. Invite links can still be copied and shared, but invited users
          will not receive an email.
        </Note>
      ) : null}
      {!state.site_url_configured ? (
        <Note tone="warning">
          Invite links use the address you are browsing from. Set a public Site URL so guests can
          open them.
        </Note>
      ) : null}

      <form onSubmit={handleCreate}>
        <label className="od-acct__field">
          <span className="od-acct__label">Email address (optional)</span>
          <input
            className="od-acct__input"
            type="email"
            placeholder="someone@example.com"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <p className="od-acct__hint">
          {/* The honest version of "invites need SMTP". They never did — the
              link works pasted into a chat window, and only the delivery of it
              needed a mail server. */}
          {state.smtp_enabled
            ? 'Leave this blank to create a link you can pass on yourself instead of sending mail.'
            : 'Email is not configured on this server, so invites are created as links for you to pass on.'}
          {state.site_url_configured
            ? ' Recipients open the link and create their own account.'
            : ' Links use the address you are browsing from until a public site URL is set in admin settings. Recipients open the link and create their own account.'}
        </p>

        <div className="od-acct__actions">
          <button
            type="submit"
            className="od-cbtn od-cbtn--primary"
            disabled={busy || (!state.unlimited && (state.remaining ?? 0) <= 0)}
          >
            {busy ? 'Creating…' : email.trim() ? 'Send invite' : 'Create invite link'}
          </button>
          <span className="od-acct__hint">
            {state.unlimited
              ? `Unlimited invites · links last ${state.ttl_hours} hours`
              : `${state.remaining} of ${state.quota} invites left · links last ${state.ttl_hours} hours`}
          </span>
        </div>
      </form>

      <ul className="od-acct__list od-acct__list--follow">
        {state.invites.length === 0 ? (
          <p className="od-acct__empty">No active invites yet.</p>
        ) : (
          state.invites.map((invite) => (
            <li key={invite.token} className="od-acct__row">
              <div className="od-acct__row-main">
                <p className="od-acct__row-title">{invite.email || 'Link invite'}</p>
                <p className={`od-acct__row-sub${invite.expired ? ' od-acct__row-sub--warn' : ''}`}>
                  {invite.expired
                    ? `Expired ${formatWhen(invite.expires_at)}`
                    : `Expires ${formatWhen(invite.expires_at)}`}
                </p>
                <code className="od-acct__link">{invite.url}</code>
              </div>
              <button type="button" className="od-cbtn" onClick={() => copyText(invite.url)}>
                Copy link
              </button>
              <button type="button" className="od-cbtn" onClick={() => handleRevoke(invite.token)}>
                Revoke
              </button>
            </li>
          ))
        )}
      </ul>
    </>
  )
}

/* ----------------------------------------------------------------- tokens */
