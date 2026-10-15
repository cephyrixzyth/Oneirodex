import { useCallback, useEffect, useState, type FormEvent } from 'react'

import { getJson, putJson } from '../api/adminApi'
import { AdminPageActions } from '../components/AdminPageActions'
import { CreateUserForm } from '../components/CreateUserForm'
import { DataTable } from '../components/DataTable'
import { Button, PageStatus } from '@oneirodex/ui'
import { MetricStrip } from '../components/opsWidgets'
import { PM_IGNORE } from '../components/formIgnore'
import { errorText } from '../utils/errorText'
import { showToast } from '../utils/toast'

const ROLES = ['user', 'librarian', 'child', 'admin']

interface AdminUser {
  id: string
  name: string
  email?: string
  role: string
  state?: boolean
  is_email_verified?: boolean
}

/** Roster counts for the metric strip (GT-C2). Pure so it can be tested directly. */
export function summarizeUsers(users: unknown) {
  const rows: AdminUser[] = Array.isArray(users) ? users : []
  const admins = rows.filter((u) => u.role === 'admin').length
  const inactive = rows.filter((u) => !u.state).length
  const unverified = rows.filter((u) => !u.is_email_verified).length
  return { total: rows.length, admins, inactive, unverified }
}

function UserEditor({
  user,
  onClose,
  onSaved,
}: {
  user: AdminUser
  onClose?: () => void
  onSaved?: () => void
}) {
  const [role, setRole] = useState(user.role)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      await putJson(`/admin/api/user/${user.id}`, { role })
      showToast(`Saved ${user.name}.`, 'success')
      onSaved?.()
      onClose?.()
    } catch (err) {
      setError(errorText(err) || 'Could not save that account.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="od-admin-panel" data-form-type="other" onSubmit={handleSubmit}>
      <h2>Edit {user.name}</h2>
      {error ? <PageStatus error={error} /> : null}
      <label className="od-admin-field">
        Role
        <select
          className="od-admin-input"
          value={role}
          onChange={(event) => setRole(event.target.value)}
          {...PM_IGNORE}
        >
          {ROLES.map((item) => (
            <option key={item} value={item}>
              {item}
            </option>
          ))}
        </select>
      </label>
      <div className="od-admin-actions-row">
        <Button type="submit" disabled={busy}>
          Save
        </Button>
        <Button onClick={onClose} disabled={busy}>
          Cancel
        </Button>
      </div>
    </form>
  )
}

export function UsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [error, setError] = useState<unknown>(null)
  // Distinct from "empty" on purpose — the old copy said "Loading or no users",
  // which left an admin unable to tell a slow request from an empty household.
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<AdminUser | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    getJson('/admin/api/users')
      .then((data) => setUsers(Array.isArray(data.users) ? data.users : []))
      .catch((err) => setError(err))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const counts = summarizeUsers(users)

  return (
    <div className="od-admin-page">
      <h1>Users &amp; access</h1>
      <p className="od-admin-lede">
        Household accounts from <code>/admin/api/users</code>. Change a member&apos;s role here.
      </p>

      <AdminPageActions label="User actions">
        <a className="od-btn" href="/admin/invites">
          Invites
        </a>
        <a className="od-btn" href="/admin/support">
          Support inbox
        </a>
        <a className="od-btn" href="/admin/manage_invites">
          Invite quotas
        </a>
      </AdminPageActions>

      <CreateUserForm onCreated={load} title="Create user" />

      <PageStatus error={error} errorMessage="Unable to load users." onRetry={load} />

      {!error && !loading ? (
        <MetricStrip
          label="Roster"
          items={[
            {
              id: 'total',
              label: 'Accounts',
              value: counts.total,
              hint: 'in household',
              tone: 'info',
            },
            {
              id: 'admins',
              label: 'Admins',
              value: counts.admins,
              hint: 'full access',
              tone: 'info',
            },
            {
              id: 'inactive',
              label: 'Inactive',
              value: counts.inactive,
              hint: 'cannot sign in',
              tone: counts.inactive > 0 ? 'warning' : 'good',
            },
            {
              id: 'unverified',
              label: 'Unverified',
              value: counts.unverified,
              hint: 'email pending',
              tone: counts.unverified > 0 ? 'warning' : 'good',
            },
          ]}
        />
      ) : null}

      <PageStatus loading={loading} loadingMessage="Loading accounts…" />

      {editing ? (
        <UserEditor user={editing} onClose={() => setEditing(null)} onSaved={load} />
      ) : null}

      {!loading && !error && users.length === 0 ? (
        <p className="od-empty">No accounts yet. Create a user above, or send an invite.</p>
      ) : null}

      {users.length > 0 ? (
        <DataTable
          columns={[
            { key: 'name', label: 'Name' },
            { key: 'email', label: 'Email' },
            { key: 'role', label: 'Role' },
            // Sort/filter on the word shown, so typing "yes" filters as expected.
            { key: 'state', label: 'Active', value: (u) => (u.state ? 'yes' : 'no') },
            {
              key: 'is_email_verified',
              label: 'Email verified',
              value: (u) => (u.is_email_verified ? 'yes' : 'no'),
            },
            {
              key: 'actions',
              label: 'Actions',
              sortable: false,
              filterable: false,
              render: (u) => (
                <Button aria-label={`Edit ${u.name} account`} onClick={() => setEditing(u)}>
                  Edit
                </Button>
              ),
            },
          ]}
          rows={users}
          getRowKey={(u) => u.id}
          caption="Household accounts"
          scrollLabel="Household accounts table"
          toolbar={false}
          columnFilters
          showCount={false}
          dense
          emptyMessage="No accounts yet."
        />
      ) : null}
    </div>
  )
}
