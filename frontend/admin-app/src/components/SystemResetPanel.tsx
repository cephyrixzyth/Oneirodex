import { useCallback, useEffect, useState } from 'react'

import { adminError, csrfHeaders } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { PageStatus, Button } from '@oneirodex/ui'

const ENDPOINT = '/admin/api/system/reset'
const CONFIRM_PHRASE = 'RESET ONEIRODEX'
const CONFIRM_ALIASES = new Set([CONFIRM_PHRASE])

interface ResetScope {
  id: string
  title: string
  blurb: string
  implies?: string[]
}

interface ResetPlan {
  table_count: number
  tables: string[]
  cascaded?: string[]
}

interface ResetDone {
  table_count: number
  actor_restored?: boolean
}

/**
 * What each scope means, in the operator's terms rather than the schema's.
 *
 * `implies` mirrors SCOPE_IMPLIES on the server. Duplicated deliberately: the
 * checkbox has to reflect the dependency the moment it is ticked, and waiting
 * for a round trip to reveal that "libraries" also clears the catalog would let
 * someone confirm a reset larger than the one they read.
 */
const SCOPES: ResetScope[] = [
  {
    id: 'catalog',
    title: 'Library catalog & scan state',
    blurb:
      'Games, matches, unmatched folders, scan jobs and artwork records. Your library folders stay configured, so you can rescan straight away.',
  },
  {
    id: 'libraries',
    title: 'Library definitions',
    blurb:
      'The configured libraries themselves, plus their filters and access grants. You will re-add the folder paths afterwards.',
    implies: ['catalog'],
  },
  {
    id: 'users',
    title: 'Member accounts — and everything linked to a member',
    blurb:
      'Members, invites, favorites, collections, playtime, chat and saves. Your own admin account is kept so you stay signed in. ' +
      'Reaches further than it sounds: anything recording who did it goes too — announcements, newsletters, support tickets, ' +
      'unmatched folders, PC cheats, reference sets and the system event log all carry a member reference.',
  },
  {
    id: 'settings',
    title: 'Settings & integrations',
    blurb:
      'Server settings, IGDB / SMTP / API credentials, themes, discovery sections and announcements return to defaults.',
  },
]

/**
 * Danger zone: scoped factory reset (GT-B32).
 *
 * Two-step by construction, not by politeness. The panel cannot perform a reset
 * without first asking the server what that reset would empty, and it shows
 * that answer — including tables reached by cascade — before the confirm field
 * is even usable. The alternative, a button that describes itself, is how an
 * operator ends up clearing something the wording did not cover.
 *
 * The one promise worth repeating everywhere it can be read: this never deletes
 * files. Scanned games, artwork and firmware live on disk and are not touched.
 * The server enforces that by having no filesystem access in the reset path at
 * all — see oneirodex/utils/system_reset.py — so this is a description of a
 * guarantee rather than a claim the UI is making on its own.
 */
export function SystemResetPanel() {
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [plan, setPlan] = useState<ResetPlan | null>(null)
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<ResetDone | null>(null)
  const [counts, setCounts] = useState<Record<string, number | null>>({})
  /** Explicit gate before preview — stops a mis-click from even planning a wipe. */
  const [acknowledged, setAcknowledged] = useState(false)

  const toggle = useCallback((scope: ResetScope) => {
    setSelected((previous) => {
      const next = new Set(previous)
      if (next.has(scope.id)) {
        next.delete(scope.id)
      } else {
        next.add(scope.id)
        // Tick the scopes this one drags in, so the list the operator reads is
        // the list that will actually be cleared.
        for (const implied of scope.implies || []) next.add(implied)
      }
      return next
    })
    // Any change invalidates the preview — confirming against a stale plan
    // would be confirming a different reset than the one shown.
    setPlan(null)
    setConfirm('')
    setDone(null)
  }, [])

  /* Each scope's real blast radius, shown on the checkbox itself.
     A scope name is a summary, and some of them badly understate what the
     database will actually empty — clearing members also clears everything that
     records *who did it*, which is 44 tables, not the handful the label implies.
     Burying that in the expanded plan meant the number arrived after the choice
     had already been made. Preview calls are read-only, so asking for all four
     up front costs nothing and the count is on screen before the first tick. */
  useEffect(() => {
    let cancelled = false

    Promise.all(
      SCOPES.map(async (scope) => {
        try {
          const response = await fetch(ENDPOINT, {
            method: 'POST',
            credentials: 'same-origin',
            headers: csrfHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ scopes: [scope.id] }),
          })
          if (!response.ok) return [scope.id, null]
          const data = await response.json()
          return [scope.id, data.table_count ?? null]
        } catch {
          // A missing count is not worth an error banner — the plan step still
          // reports the full list before anything can be confirmed.
          return [scope.id, null]
        }
      }),
    ).then((pairs) => {
      if (!cancelled) setCounts(Object.fromEntries(pairs))
    })

    return () => {
      cancelled = true
    }
  }, [])

  async function post(body: Record<string, unknown>) {
    const response = await fetch(ENDPOINT, {
      method: 'POST',
      credentials: 'same-origin',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw adminError(data, response.status, ENDPOINT)
    return data
  }

  async function preview() {
    setBusy(true)
    setError(null)
    try {
      setPlan(await post({ scopes: [...selected] }))
    } catch (exc) {
      setError(errorText(exc))
    } finally {
      setBusy(false)
    }
  }

  async function perform() {
    setBusy(true)
    setError(null)
    try {
      const result = await post({ scopes: [...selected], confirm })
      setDone(result)
      setPlan(null)
      setConfirm('')
      setSelected(new Set())
    } catch (exc) {
      setError(errorText(exc))
    } finally {
      setBusy(false)
    }
  }

  const chosen = selected.size > 0
  const confirmed = CONFIRM_ALIASES.has(confirm)

  return (
    <section className="od-ops-panel od-ops-panel--wide od-danger-zone">
      <h2>Reset this install</h2>
      <p className="od-danger-zone__lede">
        Clears Oneirodex&rsquo;s database. <strong>No files are deleted.</strong> Everything on disk
        — your scanned games, artwork you supplied and BIOS files — is left exactly as it is, so a
        rescan rebuilds the catalog.
      </p>

      <label className="od-danger-zone__ack">
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(event) => {
            setAcknowledged(event.target.checked)
            setPlan(null)
            setConfirm('')
          }}
        />
        <span>I understand this cannot be undone and I am on the correct Oneirodex install.</span>
      </label>

      <ul className="od-danger-zone__scopes">
        {SCOPES.map((scope) => (
          <li key={scope.id}>
            <label>
              <input
                type="checkbox"
                checked={selected.has(scope.id)}
                onChange={() => toggle(scope)}
                disabled={!acknowledged}
              />
              <span className="od-danger-zone__scope-title">{scope.title}</span>
              {counts[scope.id] ? (
                <span className="od-danger-zone__scope-count">
                  clears {counts[scope.id]} tables
                </span>
              ) : null}
            </label>
            <p className="od-danger-zone__scope-blurb">{scope.blurb}</p>
          </li>
        ))}
      </ul>

      <div className="od-btn-bar">
        <Button type="button" disabled={!acknowledged || !chosen || busy} onClick={preview}>
          Show me what this clears
        </Button>
      </div>

      {plan ? (
        <PageStatus announcement="status" className={'od-danger-zone__plan'}>
          <p>
            This will empty <strong>{plan.table_count}</strong> table
            {plan.table_count === 1 ? '' : 's'}
            {plan.cascaded?.length
              ? `, including ${plan.cascaded.length} reached because they reference the others`
              : ''}
            . It cannot be undone.
          </p>
          <details>
            <summary>Show every table</summary>
            <code>{[...plan.tables, ...(plan.cascaded || [])].sort().join(', ')}</code>
          </details>

          <label className="od-danger-zone__confirm">
            Type <code>{CONFIRM_PHRASE}</code> to confirm:
            <input
              type="text"
              value={confirm}
              autoComplete="off"
              spellCheck="false"
              onChange={(event) => setConfirm(event.target.value)}
            />
          </label>

          <div className="od-btn-bar">
            <Button type="button" variant="danger" disabled={!confirmed || busy} onClick={perform}>
              {busy ? 'Resetting…' : 'Reset now'}
            </Button>
          </div>
        </PageStatus>
      ) : null}

      {done ? (
        <PageStatus announcement="status" className="od-danger-zone__done">
          Reset complete — {done.table_count} table
          {done.table_count === 1 ? '' : 's'} cleared
          {done.actor_restored ? ', your admin account was kept' : ''}. No files were touched.
          Reload to see the empty install.
        </PageStatus>
      ) : null}

      {/* The plan and done blocks above stay hand-rolled: one is a disclosure
          the operator reads before confirming, the other a completion report.
          Neither is a page loading/error state. */}
      <PageStatus error={error} />
    </section>
  )
}

export default SystemResetPanel
