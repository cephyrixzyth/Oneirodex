import { useEffect, useState } from 'react'
import { Button, PageStatus, confirmAction } from '@oneirodex/ui'
import { getJson, postJson } from '../api/adminApi'
import { DataTable, type DataTableColumn } from './DataTable'

type ProposalCandidate = { igdb_id?: number | string; name?: string; score?: number }

type ProposalRow = {
  game_uuid?: string
  game_name?: string
  library_uuid?: string
  library_name?: string
  path?: string
  proposal?: { guessed_name?: string; candidates?: ProposalCandidate[] }
}

export function LibraryProposalsPanel() {
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState<ProposalRow[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(false)
  const [approvingPath, setApprovingPath] = useState('')
  const [approvalError, setApprovalError] = useState<unknown>(null)
  const [approved, setApproved] = useState<Array<{ name: string; href: string }>>([])

  async function load(signal?: AbortSignal) {
    setLoading(true)
    setError(null)
    try {
      const result = await getJson('/api/library_tools/proposals', { signal })
      setRows(Array.isArray(result?.proposals) ? result.proposals : [])
    } catch (err) {
      if (!signal?.aborted) setError(err)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }

  async function approve(row: ProposalRow, candidate: ProposalCandidate) {
    if (!row.path || candidate.igdb_id === undefined || candidate.igdb_id === null || approvingPath)
      return
    const name = candidate.name || 'this suggestion'
    const confirmed = await confirmAction({
      title: 'Approve suggested match?',
      body: [
        `Approve ${name} for ${row.game_name || row.proposal?.guessed_name || 'this folder'}?`,
        `This clears the proposal sidecar. The game is not imported until you complete the identify form.`,
        row.path,
      ],
      confirmLabel: 'Approve and identify',
      tone: 'neutral',
    })
    if (!confirmed) return
    setApprovingPath(row.path)
    setApprovalError(null)
    try {
      await postJson('/api/library_tools/proposals/approve', {
        path: row.path,
        igdb_id: candidate.igdb_id,
      })
      const params = new URLSearchParams({
        full_disk_path: row.path,
        igdb_id: String(candidate.igdb_id),
        ...(row.library_uuid ? { library_uuid: row.library_uuid } : {}),
      })
      setApproved((previous) => [
        {
          name: row.game_name || row.proposal?.guessed_name || name,
          href: `/add_game_manual?${params}`,
        },
        ...previous.filter((item) => item.href !== `/add_game_manual?${params}`),
      ])
      await load()
    } catch (err) {
      setApprovalError(err)
    } finally {
      setApprovingPath('')
    }
  }

  useEffect(() => {
    if (!open) return undefined
    const controller = new AbortController()
    void load(controller.signal)
    return () => controller.abort()
  }, [open])

  const columns: DataTableColumn[] = [
    {
      key: 'game_name',
      label: 'Game',
      value: (row) => row.game_name || row.proposal?.guessed_name || 'Unknown',
    },
    { key: 'library_name', label: 'Library', value: (row) => row.library_name || '—' },
    {
      key: 'path',
      label: 'Folder',
      render: (row) => (row.path ? <code>{row.path}</code> : '—'),
    },
    {
      key: 'candidates',
      label: 'Suggestions',
      render: (row) => {
        const candidates = row.proposal?.candidates || []
        return candidates.length ? (
          <div
            className="od-admin-panel__toolbar"
            role="group"
            aria-label={`Suggested matches for ${row.game_name || row.proposal?.guessed_name || 'folder'}`}
          >
            {candidates.map((candidate: ProposalCandidate) => (
              <Button
                key={`${candidate.igdb_id || candidate.name}-${candidate.score}`}
                type="button"
                className="od-btn--secondary"
                disabled={
                  !candidate.igdb_id || approvingPath === row.path || Boolean(approvingPath)
                }
                onClick={() => void approve(row, candidate)}
              >
                Approve {candidate.name || 'unnamed'} ({candidate.score ?? '—'})
              </Button>
            ))}
          </div>
        ) : (
          'No candidates'
        )
      },
    },
  ]

  return (
    <section
      className="od-admin-panel od-library-proposals"
      aria-labelledby="od-library-proposals-title"
    >
      <div className="od-admin-panel__toolbar">
        <div>
          <h2 id="od-library-proposals-title" className="od-admin-panel-title">
            Suggested fixes
          </h2>
          <p className="od-admin-lede">
            Review suggested matches. Approving clears the sidecar and opens the existing identify
            form; it does not import a game.
          </p>
        </div>
        <Button
          type="button"
          className="od-btn--secondary"
          aria-expanded={open}
          aria-controls="od-library-proposals-content"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? 'Hide suggestions' : 'Review suggested fixes'}
        </Button>
      </div>
      {open ? (
        <div id="od-library-proposals-content" className="od-library-proposals__content">
          <PageStatus
            loading={loading}
            loadingMessage="Loading suggestions…"
            error={error}
            errorMessage="Unable to load suggestions."
          />
          {error ? (
            <Button type="button" className="od-btn--secondary" onClick={() => void load()}>
              Retry
            </Button>
          ) : null}
          {approvalError ? (
            <PageStatus error={approvalError} errorMessage="Unable to approve this suggestion." />
          ) : null}
          {approved.length ? (
            <div aria-label="Approved suggestions" role="region">
              <h3 className="od-admin-panel-title">Ready to identify</h3>
              <ul>
                {approved.map((item) => (
                  <li key={item.href}>
                    {item.name} —{' '}
                    <a className="od-cbtn" href={item.href}>
                      Continue identify
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {!loading && !error && rows ? (
            <DataTable
              rows={rows}
              getRowKey={(row) =>
                row.game_uuid || row.path || `${row.game_name}-${row.library_name}`
              }
              caption="Suggested fixes"
              scrollLabel="Suggested fixes table"
              emptyMessage="No suggested fixes were found."
              initialSort={{ key: 'game_name', dir: 'asc' }}
              dense
              columns={columns}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
