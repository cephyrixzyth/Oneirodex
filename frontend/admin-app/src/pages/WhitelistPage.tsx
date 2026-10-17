import { useEffect, useState, type FormEvent } from 'react'
import { Button, DataTable, PageStatus, confirmAction, type DataTableColumn } from '@oneirodex/ui'
import { getJson, postJson, deleteJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { Page } from '../components/Page'

type Entry = { id: number; email: string; is_registered: boolean }

export function WhitelistPage() {
  const [entries, setEntries] = useState<Entry[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  async function reload() {
    const data = await getJson('/admin/api/whitelist')
    setEntries(Array.isArray(data.entries) ? data.entries : [])
  }
  useEffect(() => {
    reload()
      .catch((err) => setError(errorText(err)))
      .finally(() => setLoading(false))
  }, [])
  async function add(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await postJson('/admin/api/whitelist', { email: email.trim() })
      setEmail('')
      await reload()
      setMessage('Email added to the whitelist.')
    } catch (err) {
      setError(errorText(err) || 'Unable to add email.')
    } finally {
      setBusy(false)
    }
  }
  async function remove(entry: Entry) {
    if (busy) return
    const confirmed = await confirmAction({
      title: 'Remove whitelist entry?',
      body: `Remove ${entry.email} from the whitelist?`,
      confirmLabel: 'Remove entry',
      cancelLabel: 'Keep entry',
    })
    if (!confirmed) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await deleteJson(`/admin/whitelist/${entry.id}`)
      await reload()
      setMessage('Whitelist entry removed.')
    } catch (err) {
      setError(errorText(err) || 'Unable to remove entry.')
    } finally {
      setBusy(false)
    }
  }
  const columns: DataTableColumn[] = [
    { key: 'email', label: 'Email' },
    {
      key: 'is_registered',
      label: 'Registration status',
      render: (entry: Entry) => (entry.is_registered ? 'Registered' : 'Not registered'),
    },
    {
      key: 'actions',
      label: 'Actions',
      sortable: false,
      render: (entry: Entry) => (
        <Button
          disabled={busy}
          variant="danger"
          aria-label={`Remove ${entry.email} from whitelist`}
          onClick={() => remove(entry)}
        >
          Remove
        </Button>
      ),
    },
  ]
  return (
    <Page
      title="Whitelist"
      lede={
        <>
          Grant self-registration to selected email addresses. <a href="/admin/invites">Invites</a>{' '}
          can also grant access.
        </>
      }
    >
      <PageStatus error={error || null} />
      {message ? <PageStatus announcement="status">{message}</PageStatus> : null}
      <form className="od-admin-panel" onSubmit={add}>
        <label className="od-admin-field">
          Email address
          <input
            className="od-admin-input"
            type="email"
            required
            maxLength={120}
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <Button type="submit" disabled={busy || loading}>
          {busy ? 'Saving…' : 'Add email'}
        </Button>
      </form>
      <DataTable
        columns={columns}
        rows={entries}
        getRowKey={(entry) => entry.id}
        caption="Registration whitelist"
        scrollLabel="Registration whitelist table"
        emptyMessage={loading ? 'Loading whitelist…' : 'No whitelist entries.'}
      />
    </Page>
  )
}
