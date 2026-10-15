import { useState } from 'react'
import { Button, PageStatus, confirmAction } from '@oneirodex/ui'
import { getJson, postJson } from '../api/adminApi'
import { DataTable, type DataTableColumn } from './DataTable'

type GameHit = {
  uuid?: string
  game_uuid?: string
  name?: string
  full_disk_path?: string
  path?: string
}
type PlanItem = { kind?: string; from_path?: string; to_path?: string }

const RENAME_PATTERNS = [
  '{title}',
  '{title} ({year})',
  '{title} [{year}]',
  '{title} ({year}) [PC]',
  '{title} - {year}',
  '{year} - {title}',
  '{title} ({year}) (GOG)',
  '{title} ({year}) (Steam)',
  '{title} v{year}',
  '{title} ({year}) [Repack]',
]

export function RenameGamePanel() {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<GameHit[]>([])
  const [selected, setSelected] = useState<GameHit | null>(null)
  const [title, setTitle] = useState('')
  const [year, setYear] = useState('')
  const [template, setTemplate] = useState(RENAME_PATTERNS[0])
  const [renameRoot, setRenameRoot] = useState(true)
  const [renameMedia, setRenameMedia] = useState(false)
  const [moveBucket, setMoveBucket] = useState(false)
  const [plan, setPlan] = useState<PlanItem[] | null>(null)
  const [checked, setChecked] = useState<Set<number>>(() => new Set())
  const [searching, setSearching] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [status, setStatus] = useState('')

  function clearPlan() {
    setPlan(null)
    setChecked(new Set())
    setStatus('')
    setError(null)
  }

  async function searchGames() {
    const term = query.trim()
    setHits([])
    setSelected(null)
    setTitle('')
    clearPlan()
    if (!term) return
    setSearching(true)
    setError(null)
    try {
      const result = await getJson(`/api/admin/games_search?q=${encodeURIComponent(term)}`)
      const list = Array.isArray(result) ? result : result?.games || result?.results || []
      setHits(Array.isArray(list) ? list : [])
      if (!list.length) setStatus('No games matched that search.')
    } catch (err) {
      setError(err)
    } finally {
      setSearching(false)
    }
  }

  async function previewRename() {
    if (!selected) return
    setBusy(true)
    setError(null)
    setStatus('')
    try {
      const result = await postJson('/api/library_tools/rename/preview', {
        game_uuid: selected.uuid || selected.game_uuid,
        ...(title.trim() ? { title: title.trim() } : {}),
        ...(year.trim() ? { year: year.trim() } : {}),
        template,
        rename_root: renameRoot,
        rename_top_level_media: renameMedia,
        move_letter_bucket: moveBucket,
      })
      const nextPlan = Array.isArray(result?.plan) ? result.plan : []
      setPlan(nextPlan)
      setChecked(new Set(nextPlan.map((_: PlanItem, index: number) => index)))
      setStatus(
        nextPlan.length
          ? `${nextPlan.length} rename operation${nextPlan.length === 1 ? '' : 's'} previewed.`
          : 'No changes are needed.',
      )
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function applyRename() {
    if (!selected || !plan?.length || !checked.size || busy) return
    const chosen = plan.filter((_, index) => checked.has(index))
    const confirmed = await confirmAction({
      title: `Apply ${chosen.length} rename operation${chosen.length === 1 ? '' : 's'}?`,
      body: [
        `This changes the selected game’s real folder or media paths. Review the preview before continuing.`,
        ...chosen.slice(0, 3).map((item) => `${item.from_path || ''} → ${item.to_path || ''}`),
        ...(chosen.length > 3 ? [`And ${chosen.length - 3} more operation(s).`] : []),
      ],
      confirmLabel: 'Apply selected renames',
      tone: 'danger',
    })
    if (!confirmed) return
    setBusy(true)
    setError(null)
    setStatus('')
    try {
      const result = await postJson('/api/library_tools/rename/apply', {
        game_uuid: selected.uuid || selected.game_uuid,
        plan: chosen,
      })
      const results = Array.isArray(result?.results) ? result.results : []
      const succeeded = results.filter((item: { ok?: boolean }) => item.ok).length
      setStatus(
        `Rename complete: ${succeeded} succeeded, ${results.length - succeeded} failed. Preview again before another change.`,
      )
      setPlan(null)
      setChecked(new Set())
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const planColumns: DataTableColumn[] = [
    {
      key: 'select',
      label: 'Apply',
      sortable: false,
      filterable: false,
      render: (item) => (
        <input
          type="checkbox"
          className="form-check-input"
          checked={checked.has(Number(item.index))}
          onChange={(event) =>
            setChecked((previous) => {
              const next = new Set(previous)
              if (event.target.checked) next.add(Number(item.index))
              else next.delete(Number(item.index))
              return next
            })
          }
          disabled={busy}
          aria-label={`Apply ${item.kind || 'rename'} operation ${Number(item.index) + 1}`}
        />
      ),
    },
    { key: 'kind', label: 'Change', value: (item) => item.kind || 'rename' },
    {
      key: 'from_path',
      label: 'Current path',
      render: (item) => <code>{item.from_path || '—'}</code>,
    },
    {
      key: 'to_path',
      label: 'Proposed path',
      render: (item) => <code>{item.to_path || '—'}</code>,
    },
  ]

  return (
    <section className="od-admin-panel od-rename-game" aria-labelledby="od-rename-game-title">
      <div className="od-admin-panel__toolbar">
        <div>
          <h2 id="od-rename-game-title" className="od-admin-panel-title">
            Rename one game
          </h2>
          <p className="od-admin-lede">
            Search a game, preview each path change, then apply only the selected operations.
          </p>
        </div>
        <Button
          type="button"
          className="od-btn--secondary"
          aria-expanded={open}
          aria-controls="od-rename-game-content"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? 'Close rename tools' : 'Open rename tools'}
        </Button>
      </div>
      {open ? (
        <div id="od-rename-game-content">
          <div className="od-rename-game__search">
            <label className="od-admin-field" htmlFor="od-rename-game-search">
              Find game
              <input
                id="od-rename-game-search"
                className="od-admin-input"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value)
                  setHits([])
                  setSelected(null)
                  clearPlan()
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    void searchGames()
                  }
                }}
                autoComplete="off"
                disabled={searching || busy}
              />
            </label>
            <Button
              type="button"
              className="od-btn--secondary"
              disabled={searching || busy || !query.trim()}
              onClick={() => void searchGames()}
            >
              {searching ? 'Searching…' : 'Search games'}
            </Button>
          </div>
          {hits.length ? (
            <div className="od-rename-game__hits" role="group" aria-label="Game search results">
              {hits.map((game) => {
                const uuid = game.uuid || game.game_uuid || ''
                const name = game.name || 'Untitled'
                const path = game.full_disk_path || game.path || ''
                return (
                  <Button
                    key={uuid}
                    type="button"
                    className={
                      (selected?.uuid || selected?.game_uuid) === uuid
                        ? 'od-btn--accent od-rename-game__hit'
                        : 'od-btn--secondary od-rename-game__hit'
                    }
                    aria-pressed={(selected?.uuid || selected?.game_uuid) === uuid}
                    onClick={() => {
                      setSelected(game)
                      setTitle(name)
                      clearPlan()
                    }}
                  >
                    <strong>{name}</strong>
                    <br />
                    <code>{uuid}</code>
                    {path ? (
                      <>
                        <br />
                        <span>{path}</span>
                      </>
                    ) : null}
                  </Button>
                )
              })}
            </div>
          ) : null}
          {selected ? (
            <>
              <div className="od-rename-game__fields">
                <label className="od-admin-field" htmlFor="od-rename-game-title-input">
                  Title override
                  <input
                    id="od-rename-game-title-input"
                    className="od-admin-input"
                    value={title}
                    onChange={(event) => {
                      setTitle(event.target.value)
                      clearPlan()
                    }}
                    disabled={busy}
                  />
                </label>
                <label className="od-admin-field" htmlFor="od-rename-game-year">
                  Year <span className="od-admin-hint">(optional)</span>
                  <input
                    id="od-rename-game-year"
                    className="od-admin-input"
                    inputMode="numeric"
                    value={year}
                    onChange={(event) => {
                      setYear(event.target.value)
                      clearPlan()
                    }}
                    disabled={busy}
                  />
                </label>
                <label className="od-admin-field" htmlFor="od-rename-game-pattern">
                  Naming pattern
                  <select
                    id="od-rename-game-pattern"
                    className="od-admin-input"
                    value={template}
                    onChange={(event) => {
                      setTemplate(event.target.value)
                      clearPlan()
                    }}
                    disabled={busy}
                  >
                    {RENAME_PATTERNS.map((pattern) => (
                      <option key={pattern} value={pattern}>
                        {pattern}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <fieldset className="od-rename-game__options" disabled={busy}>
                <legend>Include in preview</legend>
                <label className="od-admin-field od-admin-field--check">
                  <input
                    type="checkbox"
                    checked={renameRoot}
                    onChange={(event) => {
                      setRenameRoot(event.target.checked)
                      clearPlan()
                    }}
                  />{' '}
                  Rename root folder
                </label>
                <label className="od-admin-field od-admin-field--check">
                  <input
                    type="checkbox"
                    checked={renameMedia}
                    onChange={(event) => {
                      setRenameMedia(event.target.checked)
                      clearPlan()
                    }}
                  />{' '}
                  Rename matching top-level media
                </label>
                <label className="od-admin-field od-admin-field--check">
                  <input
                    type="checkbox"
                    checked={moveBucket}
                    onChange={(event) => {
                      setMoveBucket(event.target.checked)
                      clearPlan()
                    }}
                  />{' '}
                  Move to letter bucket
                </label>
              </fieldset>
              <div className="od-admin-panel__toolbar od-rename-game__actions">
                <Button
                  type="button"
                  className="od-btn--accent"
                  disabled={busy}
                  onClick={() => void previewRename()}
                >
                  {busy ? 'Working…' : 'Preview rename'}
                </Button>
                <Button
                  type="button"
                  className="od-btn--danger"
                  disabled={busy || !checked.size}
                  onClick={() => void applyRename()}
                >
                  Apply selected renames
                </Button>
              </div>
            </>
          ) : null}
          <PageStatus
            loading={busy || searching}
            loadingMessage={searching ? 'Searching games…' : 'Working…'}
            error={error}
          />
          {status ? (
            <PageStatus announcement="status" className="od-library-doctor__status">
              {status}
            </PageStatus>
          ) : null}
          {plan ? (
            <DataTable
              rows={plan.map((item, index) => ({ ...item, index }))}
              getRowKey={(item) => `${item.index}:${item.kind}:${item.from_path}:${item.to_path}`}
              caption="Rename preview"
              scrollLabel="Rename preview table"
              emptyMessage="No changes."
              dense
              columns={planColumns}
            />
          ) : null}
        </div>
      ) : null}
    </section>
  )
}
