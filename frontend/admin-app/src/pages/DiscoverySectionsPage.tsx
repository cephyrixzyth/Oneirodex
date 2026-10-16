import { Button, Modal, PageStatus } from '@oneirodex/ui'
import { Page } from '../components/Page'
import { utcInput, useDiscoverySections } from './useDiscoverySections'
import { postJson, putJson } from '../api/adminApi'
import './DiscoverySectionsPage.css'

export function DiscoverySectionsPage() {
  const {
    sections,
    options,
    loading,
    loadFailed,
    setReload,
    busy,
    error,
    setError,
    message,
    setMessage,
    editor,
    schedule,
    setSchedule,
    scheduleDraft,
    setScheduleDraft,
    query,
    setQuery,
    hits,
    setHits,
    searching,
    setSearching,
    searchRequest,
    action,
    refresh,
    openEditor,
    closeEditor,
    search,
    saveShelf,
    move,
    remove,
    disabled,
    filterOptions,
    edit,
    API,
  } = useDiscoverySections()
  return (
    <Page
      title="Discovery sections"
      lede="Reorder shelves, choose visibility, and curate manual or filtered game selections."
    >
      <PageStatus
        loading={loading}
        loadingMessage="Loading discovery sections…"
        error={!editor && !schedule ? error || null : null}
      />
      {loadFailed ? (
        <Button onClick={() => setReload((value) => value + 1)}>
          Retry loading discovery sections
        </Button>
      ) : null}
      {!editor && !schedule && message ? (
        <PageStatus announcement="status" className="od-admin-hint">
          {message}
        </PageStatus>
      ) : null}
      <Button variant="primary" disabled={disabled} onClick={() => openEditor()}>
        Add shelf
      </Button>
      <p className="od-admin-hint">
        Built-in shelves can be reordered, hidden, scheduled and pinned; their selection cannot be
        edited or deleted.
      </p>
      <ol className="od-admin-list" aria-label="Discovery shelf order">
        {sections.map((row, index) => (
          <li key={row.id} className="od-admin-panel">
            <h2 className="od-discovery-shelf-heading">{row.name}</h2>
            <p className="od-admin-hint">
              {row.section_type === 'custom'
                ? `${row.description} · ${row.count} items`
                : row.count
                  ? `${row.count} items`
                  : 'Empty'}{' '}
              · {row.is_live ? 'Live' : 'Not live'} · {row.layout}
            </p>
            <label className="od-admin-field">
              <input
                type="checkbox"
                checked={row.is_visible}
                disabled={disabled}
                onChange={(event) => {
                  const visible = event.target.checked
                  void action(async () => {
                    await postJson(`${API}/visibility`, { section_id: row.id, is_visible: visible })
                    await refresh()
                    setMessage('Shelf visibility saved.')
                  })
                }}
              />{' '}
              Visible {row.name}
            </label>
            <div className="od-admin-actions-row">
              <Button
                disabled={disabled || index === 0}
                aria-label={`Move ${row.name} up`}
                onClick={() => move(index, -1)}
              >
                Move up
              </Button>
              <Button
                disabled={disabled || index === sections.length - 1}
                aria-label={`Move ${row.name} down`}
                onClick={() => move(index, 1)}
              >
                Move down
              </Button>
              <Button
                disabled={disabled}
                aria-label={`Schedule and pin ${row.name}`}
                onClick={() => {
                  setError('')
                  setMessage('')
                  setSchedule(row)
                  setScheduleDraft({
                    layout: row.layout,
                    starts: utcInput(row.starts_at),
                    ends: utcInput(row.ends_at),
                    pin: row.pin_rank == null ? '' : String(row.pin_rank),
                  })
                }}
              >
                Schedule and pin
              </Button>
              {row.section_type === 'custom' ? (
                <>
                  <Button
                    disabled={disabled}
                    aria-label={`Edit ${row.name}`}
                    onClick={() => openEditor(row)}
                  >
                    Edit shelf
                  </Button>
                  <Button
                    variant="danger"
                    disabled={disabled}
                    aria-label={`Delete ${row.name}`}
                    onClick={() => remove(row)}
                  >
                    Delete shelf
                  </Button>
                </>
              ) : null}
            </div>
          </li>
        ))}
      </ol>
      {!loading && !sections.length && !loadFailed ? <p>No discovery shelves yet.</p> : null}
      <Modal
        open={Boolean(editor)}
        label={editor?.id ? 'Edit discovery shelf' : 'Add discovery shelf'}
        className="od-discovery-modal"
        panelClassName="od-discovery-modal__panel od-admin-panel"
        lockScroll
        closeOnEscape={!busy}
        closeOnBackdrop={!busy}
        onClose={closeEditor}
      >
        {editor ? (
          <form onSubmit={saveShelf}>
            <h2>{editor.id ? 'Edit discovery shelf' : 'Add discovery shelf'}</h2>
            <PageStatus error={error || null} />
            <fieldset className="od-admin-fieldset" disabled={busy || loadFailed}>
              <legend>Shelf selection</legend>
              <label className="od-admin-field">
                Shelf name
                <input
                  className="od-admin-input"
                  required
                  maxLength={50}
                  value={editor.name}
                  onChange={(event) => edit({ name: event.target.value })}
                />
              </label>
              <div role="group" aria-label="Shelf selection mode">
                <label>
                  <input
                    type="radio"
                    name="shelf-mode"
                    checked={editor.mode === 'manual'}
                    onChange={() => {
                      edit({ mode: 'manual' })
                      searchRequest.current += 1
                      setSearching(false)
                    }}
                  />{' '}
                  Manual game list
                </label>
                <label>
                  <input
                    type="radio"
                    name="shelf-mode"
                    checked={editor.mode === 'filter'}
                    onChange={() => {
                      edit({ mode: 'filter' })
                      searchRequest.current += 1
                      setSearching(false)
                    }}
                  />{' '}
                  Filter
                </label>
              </div>
              {editor.mode === 'manual' ? (
                <>
                  <label className="od-admin-field">
                    Add games
                    <input
                      className="od-admin-input"
                      type="search"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                          event.preventDefault()
                          void search()
                        }
                      }}
                    />
                  </label>
                  <Button disabled={searching || !query.trim()} onClick={() => void search()}>
                    {searching ? 'Searching…' : 'Search games'}
                  </Button>
                  {hits ? (
                    <div className="od-admin-actions-row" aria-label="Game search results">
                      {hits.length ? (
                        hits.map((hit) => (
                          <Button
                            key={hit.uuid}
                            disabled={
                              editor.picks.length >= 60 ||
                              editor.picks.some((pick) => pick.uuid === hit.uuid)
                            }
                            aria-label={`Add ${hit.name}`}
                            onClick={() => {
                              edit({ picks: [...editor.picks, hit] })
                              setHits(null)
                              setQuery('')
                            }}
                          >
                            {hit.name}
                          </Button>
                        ))
                      ) : (
                        <p>No library games match this search.</p>
                      )}
                    </div>
                  ) : null}
                  <h3>In this shelf ({editor.picks.length})</h3>
                  <ol className="od-admin-list">
                    {editor.picks.map((pick, index) => (
                      <li key={`${pick.uuid}-${index}`}>
                        <span>{pick.name}</span>
                        <div className="od-admin-actions-row">
                          <Button
                            disabled={index === 0}
                            aria-label={`Move selected ${pick.name} up`}
                            onClick={() => {
                              const next = [...editor.picks]
                              ;[next[index], next[index - 1]] = [next[index - 1], next[index]]
                              edit({ picks: next })
                            }}
                          >
                            Move up
                          </Button>
                          <Button
                            disabled={index === editor.picks.length - 1}
                            aria-label={`Move selected ${pick.name} down`}
                            onClick={() => {
                              const next = [...editor.picks]
                              ;[next[index], next[index + 1]] = [next[index + 1], next[index]]
                              edit({ picks: next })
                            }}
                          >
                            Move down
                          </Button>
                          <Button
                            aria-label={`Remove ${pick.name}`}
                            onClick={() =>
                              edit({
                                picks: editor.picks.filter((item) => item.uuid !== pick.uuid),
                              })
                            }
                          >
                            Remove
                          </Button>
                        </div>
                      </li>
                    ))}
                  </ol>
                  <p className="od-admin-hint">Up to 60 games, shown in this order.</p>
                  <details>
                    <summary>Paste UUIDs instead</summary>
                    <label className="od-admin-field">
                      Game UUIDs
                      <textarea
                        className="od-admin-input"
                        rows={4}
                        value={editor.picks.map((pick) => pick.uuid).join('\n')}
                        onChange={(event) => {
                          const uuids = [
                            ...new Set(event.target.value.split(/[\s,]+/).filter(Boolean)),
                          ]
                          edit({
                            picks: uuids.map(
                              (uuid) =>
                                editor.picks.find((pick) => pick.uuid === uuid) || {
                                  uuid,
                                  name: uuid,
                                },
                            ),
                          })
                        }}
                      />
                    </label>
                  </details>
                </>
              ) : (
                <>
                  <label className="od-admin-field">
                    Filter by
                    <select
                      className="od-admin-input"
                      aria-label="Filter by"
                      value={editor.filter_type}
                      onChange={(event) => {
                        const type = event.target.value
                        const value =
                          type === 'library'
                            ? options.libraries[0]?.uuid
                            : type === 'platform'
                              ? options.platforms[0]?.id
                              : options.genres[0]?.name
                        edit({ filter_type: type, filter_value: value || '' })
                      }}
                    >
                      <option value="library">Library</option>
                      <option value="platform">Platform</option>
                      <option value="genre">Genre</option>
                    </select>
                  </label>
                  <label className="od-admin-field">
                    Filter value
                    <select
                      className="od-admin-input"
                      aria-label="Filter value"
                      required
                      value={editor.filter_value}
                      onChange={(event) => edit({ filter_value: event.target.value })}
                    >
                      <option value="">Choose a value</option>
                      {filterOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                </>
              )}
            </fieldset>
            <div className="od-admin-actions-row">
              <Button
                type="submit"
                variant="primary"
                disabled={
                  busy || loadFailed || (editor.mode === 'manual' && editor.picks.length > 60)
                }
              >
                Save shelf
              </Button>
              <Button disabled={busy} onClick={closeEditor}>
                Cancel
              </Button>
            </div>
          </form>
        ) : null}
      </Modal>
      <Modal
        open={Boolean(schedule)}
        label={`Schedule and pin ${schedule?.name || ''}`}
        className="od-discovery-modal"
        panelClassName="od-discovery-modal__panel od-admin-panel"
        lockScroll
        closeOnEscape={!busy}
        closeOnBackdrop={!busy}
        onClose={() => {
          if (!busy) {
            setSchedule(null)
            setError('')
          }
        }}
      >
        {schedule ? (
          <>
            <h2>Schedule and pin {schedule.name}</h2>
            <PageStatus error={error || null} />
            {message ? (
              <PageStatus announcement="status" className="od-admin-hint">
                {message}
              </PageStatus>
            ) : null}
            <form
              onSubmit={(event) => {
                event.preventDefault()
                void action(async () => {
                  await putJson(`${API}/${schedule.id}/schedule`, {
                    layout: scheduleDraft.layout,
                    starts_at: scheduleDraft.starts ? `${scheduleDraft.starts}Z` : null,
                    ends_at: scheduleDraft.ends ? `${scheduleDraft.ends}Z` : null,
                  })
                  await refresh()
                  setMessage('Shelf schedule saved.')
                })
              }}
            >
              <fieldset className="od-admin-fieldset" disabled={busy || loadFailed}>
                <legend>Layout and UTC schedule</legend>
                <label className="od-admin-field">
                  Shelf layout
                  <select
                    className="od-admin-input"
                    aria-label="Shelf layout"
                    value={scheduleDraft.layout}
                    onChange={(event) =>
                      setScheduleDraft({ ...scheduleDraft, layout: event.target.value })
                    }
                  >
                    <option value="shelf">Shelf</option>
                    <option value="hero">Hero</option>
                    <option value="carousel">Carousel</option>
                  </select>
                </label>
                <label className="od-admin-field">
                  Starts at (UTC)
                  <input
                    className="od-admin-input"
                    type="datetime-local"
                    step={1}
                    value={scheduleDraft.starts}
                    onChange={(event) =>
                      setScheduleDraft({ ...scheduleDraft, starts: event.target.value })
                    }
                  />
                </label>
                <label className="od-admin-field">
                  Ends at (UTC)
                  <input
                    className="od-admin-input"
                    type="datetime-local"
                    step={1}
                    value={scheduleDraft.ends}
                    onChange={(event) =>
                      setScheduleDraft({ ...scheduleDraft, ends: event.target.value })
                    }
                  />
                </label>
                <p className="od-admin-hint">
                  Leave either timestamp blank to clear that boundary. Hidden shelves remain hidden.
                </p>
              </fieldset>
              <Button type="submit" variant="primary" disabled={busy || loadFailed}>
                Save schedule
              </Button>
            </form>
            <form
              onSubmit={(event) => {
                event.preventDefault()
                void action(async () => {
                  await putJson(`${API}/${schedule.id}/pin`, {
                    pin_rank: scheduleDraft.pin === '' ? null : Number(scheduleDraft.pin),
                  })
                  await refresh()
                  setMessage('Shelf pin saved.')
                })
              }}
            >
              <fieldset className="od-admin-fieldset" disabled={busy || loadFailed}>
                <legend>Reserved top block</legend>
                <label className="od-admin-field">
                  Pin rank
                  <input
                    className="od-admin-input"
                    type="number"
                    step={1}
                    min={-2147483648}
                    max={2147483647}
                    value={scheduleDraft.pin}
                    onChange={(event) =>
                      setScheduleDraft({ ...scheduleDraft, pin: event.target.value })
                    }
                  />
                </label>
                <p className="od-admin-hint">
                  Lowest ranks appear first. Only the first three forced shelves take effect. Leave
                  blank to release this shelf to its normal order.
                </p>
              </fieldset>
              <Button type="submit" disabled={busy || loadFailed}>
                Save pin
              </Button>
            </form>
            <div className="od-admin-actions-row">
              <Button
                disabled={busy}
                onClick={() => {
                  setSchedule(null)
                  setError('')
                }}
              >
                Close
              </Button>
            </div>
          </>
        ) : null}
      </Modal>
    </Page>
  )
}
