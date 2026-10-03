import { useEffect, useState } from 'react'
import { PageStatus } from '@oneirodex/ui'
import { getJson } from '../api/adminApi'
import { DataTable, type DataTableColumn } from '../components/DataTable'
import { MetricStrip } from '../components/opsWidgets'
import { CreateUserForm } from '../components/CreateUserForm'
import { Page } from '../components/Page'

interface InviteUser {
  user_id?: string
  id?: string
  name?: string
  role?: string
  invite_quota?: number
  unused_invites?: number
}

const COLUMNS: DataTableColumn[] = [
  { key: 'name', label: 'Name' },
  { key: 'role', label: 'Role' },
  {
    key: 'invite_quota',
    label: 'Quota',
    align: 'right',
    value: (u) => (u.role === 'admin' ? 'Unlimited' : u.invite_quota),
  },
  { key: 'unused_invites', label: 'Unused tokens', align: 'right' },
]

export function InvitesPage() {
  const [users, setUsers] = useState<InviteUser[]>([])
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)

  // Summed with Number() and a zero default: the API omits the field for
  // users who have never had a quota, and `undefined` would poison the total
  // into NaN rather than simply not adding to it.
  const unusedTotal = users.reduce((n, u) => n + (Number(u.unused_invites) || 0), 0)
  const quotaTotal = users.reduce((n, u) => n + (Number(u.invite_quota) || 0), 0)

  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    getJson('/admin/api/invites')
      .then((data) => setUsers(Array.isArray(data.users) ? data.users : []))
      .catch((err) => setError(err))
      .finally(() => setLoading(false))
  }, [reloadKey])

  if (error) {
    return (
      <div className="od-admin-page">
        <PageStatus error errorMessage="Unable to load invite quotas." />
      </div>
    )
  }

  return (
    <Page
      title="Invites"
      lede={
        <>
          Per-user invite quota and unused tokens. Adjust quota on the classic form if needed.
          Members can create invites as links without an email address — see their Invites panel.
          Admins can also skip invites entirely and add a member here.
        </>
      }
    >
      <CreateUserForm
        onCreated={() => setReloadKey((key) => key + 1)}
        title="Create user without invite"
      />
      <div className="od-admin-actions-row">
        <a className="od-btn" href="/admin/manage_invites">
          Classic invite editor
        </a>
        <a className="od-btn" href="/admin/users">
          Users
        </a>
        <a className="od-btn" href="/admin/support">
          Support inbox
        </a>
      </div>
      {/* UID-014. "Unused tokens" is the number that decides whether anyone
          can actually invite someone, so it carries the tone: zero across the
          household means invites are effectively closed, which the table alone
          does not say out loud. */}
      <MetricStrip
        label="Invites"
        items={[
          {
            id: 'members',
            label: 'Members',
            value: users.length,
            hint: 'with a quota',
            tone: 'info',
          },
          {
            id: 'unused',
            label: 'Unused tokens',
            value: unusedTotal,
            hint: 'invites available now',
            tone: unusedTotal === 0 ? 'warning' : 'good',
          },
          { id: 'quota', label: 'Total quota', value: quotaTotal, hint: 'allocated', tone: 'info' },
        ]}
      />
      <DataTable
        columns={COLUMNS}
        rows={users}
        getRowKey={(u) => u.user_id || u.id}
        emptyMessage={loading ? 'Loading invites…' : 'No users.'}
      />
    </Page>
  )
}
