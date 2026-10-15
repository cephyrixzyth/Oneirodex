import { useCallback, useEffect, useState } from 'react'
import { Button, DataTable, PageStatus, confirmAction, type DataTableColumn } from '@oneirodex/ui'
import { deleteJson, getJson } from '../api/adminApi'
import { Page } from '../components/Page'
import { errorText } from '../utils/errorText'

type RequestRow = {
  id: number
  username: string
  game_uuid: string
  status: string
  file_name: string | null
  request_time: string | null
  completion_time: string | null
}
const formatDate = (value: string | null) => (value ? new Date(value).toLocaleString() : 'N/A')

export function DownloadsPage() {
  const [rows, setRows] = useState<RequestRow[]>([])
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<number | null>(null)
  const [message, setMessage] = useState('')
  const [reload, setReload] = useState(0)
  const refresh = useCallback(async (signal?: AbortSignal) => {
    setLoading(true)
    setFailed(false)
    setError('')
    try {
      const data = await getJson('/api/admin/download-requests', { signal })
      if (!Array.isArray(data?.requests))
        throw new Error('Download request response was incomplete.')
      setRows(data.requests)
    } catch (err) {
      if (signal?.aborted) return
      setError(errorText(err))
      setFailed(true)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    void refresh(controller.signal)
    return () => controller.abort()
  }, [refresh, reload])
  async function remove(row: RequestRow) {
    if (busy !== null) return
    if (
      !(await confirmAction({
        title: 'Delete download request?',
        body: `Delete request ${row.id} for ${row.username}? This removes the request record.`,
        confirmLabel: 'Delete request',
        cancelLabel: 'Keep request',
      }))
    )
      return
    setBusy(row.id)
    setError('')
    setMessage('')
    try {
      await deleteJson(`/api/delete_download/${row.id}`)
      setRows((current) => current.filter((item) => item.id !== row.id))
      setMessage(`Download request ${row.id} deleted.`)
    } catch (err) {
      setError(errorText(err) || 'Could not delete download request.')
    } finally {
      setBusy(null)
    }
  }
  const columns: DataTableColumn[] = [
    { key: 'id', label: 'ID', align: 'right' },
    { key: 'username', label: 'Username' },
    { key: 'game_uuid', label: 'Game UUID (part)' },
    { key: 'status', label: 'Status' },
    { key: 'file_name', label: 'ZIP file' },
    {
      key: 'request_time',
      label: 'Request time',
      value: (row: RequestRow) => formatDate(row.request_time),
    },
    {
      key: 'completion_time',
      label: 'Completion time',
      value: (row: RequestRow) => formatDate(row.completion_time),
    },
    {
      key: 'actions',
      label: 'Actions',
      sortable: false,
      render: (row: RequestRow) => (
        <Button
          variant="danger"
          disabled={busy !== null || loading}
          aria-label={`Delete download request ${row.id}`}
          onClick={() => void remove(row)}
        >
          Delete
        </Button>
      ),
    },
  ]
  return (
    <Page title="Download requests" lede="Review zip jobs queued by members, newest first.">
      <PageStatus
        loading={loading && rows.length === 0}
        loadingMessage="Loading download requests…"
        error={error || null}
      />
      {failed ? (
        <Button disabled={loading} onClick={() => setReload((value) => value + 1)}>
          Retry loading download requests
        </Button>
      ) : null}
      {message ? <PageStatus announcement="status">{message}</PageStatus> : null}
      {!loading && !failed ? (
        <DataTable
          columns={columns}
          rows={rows}
          getRowKey={(row) => row.id}
          caption="Download requests"
          scrollLabel="Download requests table"
          emptyMessage="No download requests found."
        />
      ) : null}
    </Page>
  )
}
