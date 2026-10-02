import { useId, useRef, useState, type FormEvent } from 'react'
import { Button, PM_IGNORE } from '@oneirodex/ui'
import { useFocusRecovery } from '../../hooks/useFocusRecovery'
import type { StoreConnection, StoreConnectionAction } from '../../api/ownership'
import {
  CONNECT_FIELDS,
  CSV_HINT,
  STATE_LABEL,
  STATE_TONE,
  credentialNote,
  stateSentence,
} from './storeCopy'

export type CardMessage = { tone: 'good' | 'bad' | 'info'; text: string } | null

type Props = {
  connection: StoreConnection
  busy: string | null
  message: CardMessage
  /** The card's heading level under the page's own headings. */
  titleTag?: 'h3' | 'h4'
  onSync: () => void
  onCancel: () => void
  onConnect: (fields: Record<string, string>) => Promise<boolean>
  onDisconnect: () => void
  onImportCsv: (input: { csv: string; file: File | null }) => Promise<boolean>
  onImportFile: (file: File) => Promise<boolean>
}

/**
 * One provider in the shared connection list. Renders only the actions the
 * server listed for this state, so an unavailable store never shows a button
 * that could not work, and cancel appears only where a sync can really stop.
 */
export function StoreConnectionCard({
  connection,
  busy,
  message,
  titleTag: Title = 'h3',
  onSync,
  onCancel,
  onConnect,
  onDisconnect,
  onImportCsv,
  onImportFile,
}: Props) {
  const id = useId()
  const [panel, setPanel] = useState<'connect' | 'import' | null>(null)
  const [fields, setFields] = useState<Record<string, string>>({})
  const [csv, setCsv] = useState('')
  const fileRef = useRef<HTMLInputElement | null>(null)
  const cardRef = useRef<HTMLLIElement | null>(null)
  const headingRef = useRef<HTMLHeadingElement | null>(null)
  const connectToggleRef = useRef<HTMLButtonElement | null>(null)
  const importToggleRef = useRef<HTMLButtonElement | null>(null)
  // The panel just closed, so focus that fell out of it returns to its toggle.
  const closedPanel = useRef<'connect' | 'import' | null>(null)
  const { provider, name, state, records, actions } = connection
  const tone = STATE_TONE[state]
  const can = (action: StoreConnectionAction) => actions.includes(action)
  const working = busy !== null
  const connectFields = CONNECT_FIELDS[provider] || []
  const note = credentialNote(connection)
  const sentence = stateSentence(connection)
  const last = connection.last_sync
  const previous = connection.previous_failure
  const labelField = connectFields[0] && !connectFields[0].secret ? connectFields[0].name : null
  // A blank token changes nothing when the saved one was refused or missing,
  // and a new link without one has nothing to sync with unless the household
  // sign-in covers it. An Amazon sign-in that lacks only its device serial is
  // repaired by the serial alone, so the token is not demanded then.
  const secretRequired =
    (state === 'reauth_required' && last?.outcome?.reason !== 'device_serial_missing') ||
    state === 'needs_credential' ||
    (state === 'not_connected' && !connection.credential.household_available)

  // Sync turns into Stop while it runs, Stop goes when it ends, a panel closes
  // after Save: the button a keyboard or D-pad user was on disappears. Focus
  // that fell to the page comes back to this card.
  useFocusRecovery(
    cardRef,
    () => {
      const closed = closedPanel.current
      closedPanel.current = null
      const toggle = closed
        ? (closed === 'connect' ? connectToggleRef : importToggleRef).current
        : null
      if (toggle && !toggle.disabled) return toggle
      // An open form keeps focus: a failed save or import leaves it open, and
      // the next press should retry there, not start a sync or close the form.
      // While its request runs the submit is disabled, so park on the heading;
      // focus returns to the submit when it is enabled again.
      const submit = cardRef.current?.querySelector<HTMLButtonElement>(
        '.od-store-card__form button[type="submit"]',
      )
      if (submit) return submit.disabled ? headingRef.current : submit
      return (
        cardRef.current?.querySelector<HTMLElement>(
          '.od-store-card__actions [data-od-nav]:not([disabled])',
        ) ?? headingRef.current
      )
    },
    // The heading only holds focus while no action exists (a sync that
    // cannot be stopped); once one returns, focus moves on to it.
    headingRef,
  )

  const toggle = (next: 'connect' | 'import') => {
    setPanel((current) => (current === next ? null : next))
    // Reconnecting keeps the saved label unless the member changes it.
    const saved = connection.account.external_account_id
    if (next === 'connect' && labelField && saved) {
      setFields((current) =>
        current[labelField] === undefined ? { ...current, [labelField]: saved } : current,
      )
    }
  }

  /** Close a panel; focus that was in it returns to the button that opened it. */
  const closePanel = (which: 'connect' | 'import') => {
    setPanel(null)
    closedPanel.current = which
  }

  async function submitConnect(event: FormEvent) {
    event.preventDefault()
    if (await onConnect(fields)) {
      // Secrets never linger in the page once the server has them.
      setFields((current) =>
        Object.fromEntries(
          Object.entries(current).filter(
            ([key]) => !connectFields.find((f) => f.name === key)?.secret,
          ),
        ),
      )
      closePanel('connect')
    }
  }

  async function submitImport(event: FormEvent) {
    event.preventDefault()
    const file = fileRef.current?.files?.[0] || null
    const done =
      can('import_file') && file ? await onImportFile(file) : await onImportCsv({ csv, file })
    if (done) {
      setCsv('')
      if (fileRef.current) fileRef.current.value = ''
      closePanel('import')
    }
  }

  return (
    <li
      ref={cardRef}
      className="od-store-card"
      data-state={state}
      data-tone={tone}
      aria-labelledby={`${id}-name`}
    >
      <div className="od-store-card__head">
        <Title ref={headingRef} id={`${id}-name`} className="od-store-card__name" tabIndex={-1}>
          {name}
        </Title>
        <span className="od-store-card__badge" data-tone={tone}>
          {STATE_LABEL[state]}
        </span>
        {records.owned > 0 ? (
          <span className="od-store-card__counts">
            {records.owned} titles · {records.matched} matched
            {records.needs_review > 0 ? ` · ${records.needs_review} to review` : ''}
          </span>
        ) : null}
      </div>

      <p className="od-store-card__sentence" aria-live={state === 'syncing' ? 'polite' : undefined}>
        {sentence}
      </p>
      {state === 'syncing' ? (
        <progress className="od-store-card__progress" aria-label={`${name} sync in progress`} />
      ) : null}
      {previous?.outcome ? (
        <p className="od-store-card__note">Before you reconnected: {previous.outcome.message}</p>
      ) : null}
      {last?.outcome?.action === 'contact_admin' && state !== 'syncing' ? (
        <p className="od-store-card__note">Only your server administrator can fix this.</p>
      ) : null}
      {note &&
      (can('connect') || can('reconnect') || connection.credential.source === 'household') ? (
        <p className="od-store-card__note">{note}</p>
      ) : null}
      {message ? (
        <p
          className="od-store-card__message"
          data-tone={message.tone}
          role={message.tone === 'bad' ? 'alert' : 'status'}
        >
          {message.text}
        </p>
      ) : null}

      {actions.length ? (
        <div className="od-store-card__actions">
          {can('sync') ? (
            <Button data-od-nav size="sm" variant="primary" disabled={working} onClick={onSync}>
              {busy === 'sync'
                ? 'Syncing…'
                : state === 'failed' || state === 'cancelled' || state === 'partial'
                  ? 'Try again'
                  : 'Sync now'}
            </Button>
          ) : null}
          {can('cancel') ? (
            <Button
              data-od-nav
              size="sm"
              variant="danger"
              disabled={busy === 'cancel'}
              onClick={onCancel}
            >
              {busy === 'cancel' ? 'Stopping…' : 'Stop sync'}
            </Button>
          ) : null}
          {can('connect') || can('reconnect') ? (
            <Button
              ref={connectToggleRef}
              data-od-nav
              size="sm"
              variant={
                state === 'reauth_required' || state === 'needs_credential' ? 'primary' : 'default'
              }
              aria-expanded={panel === 'connect'}
              aria-controls={panel === 'connect' ? `${id}-connect` : undefined}
              disabled={working}
              onClick={() => toggle('connect')}
            >
              {can('connect') ? 'Link account' : 'Reconnect'}
            </Button>
          ) : null}
          {can('import_csv') || can('import_file') ? (
            <Button
              ref={importToggleRef}
              data-od-nav
              size="sm"
              aria-expanded={panel === 'import'}
              aria-controls={panel === 'import' ? `${id}-import` : undefined}
              disabled={working}
              onClick={() => toggle('import')}
            >
              {can('import_file') ? `Import ${connection.name} export` : 'Import a list'}
            </Button>
          ) : null}
          {can('disconnect') ? (
            <Button data-od-nav size="sm" variant="quiet" disabled={working} onClick={onDisconnect}>
              {connection.account.connected ? 'Disconnect' : 'Clear imported titles'}
            </Button>
          ) : null}
        </div>
      ) : null}

      {panel === 'connect' ? (
        <form
          id={`${id}-connect`}
          className="od-store-card__form"
          data-form-type="other"
          onSubmit={submitConnect}
        >
          {connectFields.map((field) => (
            <label key={field.name}>
              {field.label}
              {field.kind === 'secret-multiline' ? (
                <textarea
                  {...PM_IGNORE}
                  rows={3}
                  autoComplete="off"
                  spellCheck={false}
                  required={Boolean(field.secret && secretRequired)}
                  value={fields[field.name] ?? ''}
                  placeholder={field.placeholder}
                  onChange={(event) =>
                    setFields((c) => ({ ...c, [field.name]: event.target.value }))
                  }
                />
              ) : (
                <input
                  {...PM_IGNORE}
                  type={field.kind === 'secret' ? 'password' : 'text'}
                  // Browsers ignore autocomplete="off" on a password field and
                  // would offer (or save) the member's site password here.
                  autoComplete={field.kind === 'secret' ? 'one-time-code' : 'off'}
                  inputMode={field.kind === 'numeric' ? 'numeric' : undefined}
                  pattern={field.kind === 'numeric' ? '[0-9]+' : undefined}
                  required={Boolean(field.required || (field.secret && secretRequired))}
                  value={fields[field.name] ?? ''}
                  placeholder={field.placeholder}
                  onChange={(event) =>
                    setFields((c) => ({ ...c, [field.name]: event.target.value }))
                  }
                />
              )}
            </label>
          ))}
          <p className="od-store-card__note">
            Paste what your launcher tool produced. Oneirodex never asks for your store password,
            and a saved token is never shown again.
          </p>
          <div className="od-store-card__actions">
            <Button data-od-nav type="submit" size="sm" variant="primary" disabled={working}>
              {busy === 'connect' ? 'Saving…' : 'Save link'}
            </Button>
            <Button data-od-nav size="sm" variant="quiet" onClick={() => closePanel('connect')}>
              Close
            </Button>
          </div>
        </form>
      ) : null}

      {panel === 'import' ? (
        <form id={`${id}-import`} className="od-store-card__form" onSubmit={submitImport}>
          {can('import_csv') ? (
            <label>
              Paste a list (one ID per line, optionally ID,name)
              <textarea
                rows={4}
                value={csv}
                placeholder={CSV_HINT[provider]}
                onChange={(event) => setCsv(event.target.value)}
              />
            </label>
          ) : null}
          <label>
            {can('import_file')
              ? `${connection.name} export (.json or .csv)`
              : 'Or choose a CSV file'}
            <input
              type="file"
              ref={fileRef}
              accept={can('import_file') ? '.json,.csv,application/json,text/csv' : '.csv,text/csv'}
            />
          </label>
          <div className="od-store-card__actions">
            <Button data-od-nav type="submit" size="sm" variant="primary" disabled={working}>
              {busy === 'import' ? 'Importing…' : 'Import'}
            </Button>
            <Button data-od-nav size="sm" variant="quiet" onClick={() => closePanel('import')}>
              Close
            </Button>
          </div>
        </form>
      ) : null}
    </li>
  )
}
