import { useEffect, useState, type FormEvent } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { getJson, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { DataTable, type DataTableColumn } from '../components/DataTable'
import { MetricStrip } from '../components/opsWidgets'
import { CreateUserForm } from '../components/CreateUserForm'
import { AdminPageActions } from '../components/AdminPageActions'
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
  const [quotaUser, setQuotaUser] = useState('')
  const [adjustment, setAdjustment] = useState('0')
  const [saving, setSaving] = useState(false)
  const [quotaError, setQuotaError] = useState('')
  const [quotaMessage, setQuotaMessage] = useState('')

  async function adjustQuota(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (saving) return
    setSaving(true)
    setQuotaError('')
    setQuotaMessage('')
    try {
      const data = await postJson('/admin/api/invites/quota', {
        user_id: quotaUser,
        invites_number: Number(adjustment),
      })
      setQuotaMessage(`Quota updated to ${data.invite_quota}.`)
      setReloadKey((key) => key + 1)
    } catch (err) {
      setQuotaError(errorText(err) || 'Could not adjust invite quota.')
    } finally {
      setSaving(false)
    }
  }

  useEffect(() => {
    setLoading(true)
    setError(null)
    getJson('/admin/api/invites')
      .then((data) => setUsers(Array.isArray(data.users) ? data.users : []))
      .catch((err) => setError(err))
      .finally(() => setLoading(false))
  }, [reloadKey])

  if (error) {
    return (
      <Page title="Invites" lede="Per-user invite quota and unused tokens.">
        <PageStatus error errorMessage="Unable to load invite quotas." />
        <Button
          type="button"
          className="od-btn--secondary"
          onClick={() => setReloadKey((key) => key + 1)}
        >
          Retry loading invites
        </Button>
      </Page>
    )
  }

  return (
    <Page
      title="Invites"
      lede={
        <>
          Per-user invite quota and unused tokens. Add or subtract quota below. Members can create
          invites as links without an email address — see their Invites panel. Admins can also skip
          invites entirely and add a member here.
        </>
      }
    >
      <CreateUserForm
        onCreated={() => setReloadKey((key) => key + 1)}
        title="Create user without invite"
      />
      <form className="od-admin-panel" onSubmit={adjustQuota}>
        <h2 className="od-admin-subhead">Adjust invite quota</h2>
        <label className="od-admin-field">
          Member
          <select
            className="od-admin-input"
            required
            value={quotaUser}
            onChange={(e) => setQuotaUser(e.target.value)}
          >
            <option value="">Choose a member</option>
            {users.map((user) => (
              <option key={user.user_id || user.id} value={user.user_id}>
                {user.name}
              </option>
            ))}
          </select>
        </label>
        <label className="od-admin-field">
          Quota adjustment
          <input
            className="od-admin-input"
            type="number"
            required
            min={-1000}
            max={1000}
            step={1}
            value={adjustment}
            onChange={(e) => setAdjustment(e.target.value)}
          />
        </label>
        <p className="od-admin-lede">
          Positive numbers add quota; negative numbers subtract it. Existing invite tokens are
          retained.
        </p>
        <PageStatus error={quotaError || null} />
        {quotaMessage ? <PageStatus announcement="status">{quotaMessage}</PageStatus> : null}
        <Button type="submit" disabled={saving || loading}>
          {saving ? 'Saving…' : 'Adjust quota'}
        </Button>
      </form>
      <AdminPageActions label="Invite page actions">
        <a className="od-cbtn" href="/admin/users">
          Users
        </a>
        <a className="od-cbtn" href="/admin/support">
          Support inbox
        </a>
      </AdminPageActions>
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
