import { useState } from 'react'
import { createRequest, deleteRequest, fetchRequests, resolveRequest } from '../api/wishlist'
import { ContextBar, Popover } from '../chrome/ContextBar'
import { formatLocaleDate } from '../utils/formatLocaleDate'
import { PageStatus } from '../components/PageStatus'
import './WishlistPage.css'
import { Button, useResource, useResourceMutation, useShellConfig } from '@oneirodex/ui'

const WISHLIST_QUERY_KEY = ['wishlist']

const RESOLVE_ACTIONS = [
  { status: 'approved', label: 'Approve' },
  { status: 'rejected', label: 'Reject' },
  { status: 'fulfilled', label: 'Fulfilled' },
]

export function WishlistPage() {
  const shellConfig = useShellConfig()
  const isLibrarian = Boolean(shellConfig.isLibrarian ?? shellConfig.isAdmin)
  const useNewChrome = Boolean(shellConfig.enableNewChrome)
  const [showAll, setShowAll] = useState(false)
  const [title, setTitle] = useState('')
  const [notes, setNotes] = useState('')
  const [actionError, setActionError] = useState<any>(null)
  // Separate from actionError on purpose: the create form lives inside a
  // popover and shows its own failure there, while approve / reject / cancel
  // fail against a row in the list. One state for both meant a failed request
  // painted an alert in two places at once.
  const [createError, setCreateError] = useState<any>(null)
  const [busyId, setBusyId] = useState<any>(null)
  const [submitting, setSubmitting] = useState(false)

  const all = isLibrarian && showAll

  const {
    data: requests,
    loading,
    error,
    reload,
  } = useResource(['wishlist', { all }], ({ signal }) =>
    fetchRequests({ all, signal }).then((data) =>
      Array.isArray(data.requests) ? data.requests : [],
    ),
  )

  // Each write refetches the list — `invalidateQueries(['wishlist'])` matches
  // both the `{ all: false }` and `{ all: true }` views, which is exactly the
  // old `reloadCount` bump.
  const createMutation = useResourceMutation<unknown, LooseProps>((vars) => createRequest(vars), {
    invalidate: [WISHLIST_QUERY_KEY],
  })
  const cancelMutation = useResourceMutation<unknown, string>((id) => deleteRequest(id), {
    invalidate: [WISHLIST_QUERY_KEY],
  })
  const resolveMutation = useResourceMutation<unknown, LooseProps>(
    ({ id, status }) => resolveRequest(id, { status }),
    {
      invalidate: [WISHLIST_QUERY_KEY],
    },
  )

  /**
   * @param {SubmitEvent} event
   * @param {() => void} [onDone] closes the popover, but only on success —
   *   dismissing the panel on a failed submit would take the error message
   *   with it, and the field the member has to correct.
   */
  async function handleCreate(event: any, onDone: any = undefined) {
    event.preventDefault()
    const trimmed = title.trim()
    if (!trimmed) {
      setCreateError(new Error('Enter a title before sending your request.'))
      return
    }

    setSubmitting(true)
    setCreateError(null)
    try {
      await createMutation.mutateAsync({ title: trimmed, notes: notes.trim() })
      setTitle('')
      setNotes('')
      onDone?.()
    } catch (err: any) {
      setCreateError(err)
    } finally {
      setSubmitting(false)
    }
  }

  async function handleCancel(id: any) {
    setBusyId(id)
    setActionError(null)
    try {
      await cancelMutation.mutateAsync(id)
    } catch (err: any) {
      setActionError(err)
    } finally {
      setBusyId(null)
    }
  }

  async function handleResolve(id: any, status: any) {
    setBusyId(id)
    setActionError(null)
    try {
      await resolveMutation.mutateAsync({ id, status })
    } catch (err: any) {
      setActionError(err)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      {useNewChrome ? (
        <ContextBar
          /* Views + Request a title share one fused od-cbtn-group (Library
             Apply/Clear shape). SegmentedViews would leave Request as a peer
             pill with a star; librarians need My requests | Everyone’s |
             Request a title as one outlined control. Members only get Request. */
          summary={requests ? `${requests.length} requests` : null}
          actions={
            <div className="od-cbtn-group" role="group" aria-label="Wishlist">
              {isLibrarian ? (
                <>
                  <button
                    type="button"
                    className={`od-cbtn${!showAll ? ' is-on' : ''}`}
                    aria-pressed={!showAll}
                    onClick={() => setShowAll(false)}
                  >
                    My requests
                  </button>
                  <button
                    type="button"
                    className={`od-cbtn${showAll ? ' is-on' : ''}`}
                    aria-pressed={showAll}
                    onClick={() => setShowAll(true)}
                  >
                    Everyone’s
                  </button>
                </>
              ) : null}
              {/* Quiet like Library bar peers: wash only while open. */}
              <Popover label="Request a title">
                {({ close }: LooseProps) => (
                  <form
                    className="od-wishlist__form"
                    onSubmit={(event) => handleCreate(event, close)}
                  >
                    <label htmlFor="od-wishlist-title">Title</label>
                    <input
                      id="od-wishlist-title"
                      type="text"
                      maxLength={255}
                      required
                      placeholder="Game title"
                      value={title}
                      onChange={(event) => setTitle(event.target.value)}
                    />
                    <label htmlFor="od-wishlist-notes">Notes</label>
                    <input
                      id="od-wishlist-notes"
                      type="text"
                      maxLength={400}
                      placeholder="Optional details"
                      value={notes}
                      onChange={(event) => setNotes(event.target.value)}
                    />
                    {createError ? (
                      <PageStatus error={createError} className="od-wishlist__action-error" />
                    ) : null}
                    <button
                      type="submit"
                      className="od-cbtn od-cbtn--primary"
                      disabled={submitting}
                    >
                      {submitting ? 'Requesting…' : 'Request'}
                    </button>
                  </form>
                )}
              </Popover>
            </div>
          }
        />
      ) : null}
      <div className="od-more-page od-wishlist">
        {useNewChrome ? null : (
          <>
            <div className="od-page-header od-wishlist__header">
              <div>
                <h1>Wishlist</h1>
                <p className="od-more-page__lede">
                  Request titles you’d like added to the library.
                </p>
              </div>
            </div>

            <form className="od-wishlist__form" onSubmit={handleCreate}>
              <label htmlFor="od-wishlist-title">Title</label>
              <input
                id="od-wishlist-title"
                type="text"
                maxLength={255}
                required
                placeholder="Game title"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
              <label htmlFor="od-wishlist-notes">Notes</label>
              <input
                id="od-wishlist-notes"
                type="text"
                maxLength={400}
                placeholder="Optional details"
                value={notes}
                onChange={(event) => setNotes(event.target.value)}
              />
              <Button type="submit" disabled={submitting}>
                {submitting ? 'Requesting…' : 'Request'}
              </Button>
              {createError ? (
                <PageStatus error={createError} className="od-wishlist__action-error" />
              ) : null}
            </form>
          </>
        )}

        {isLibrarian && !useNewChrome ? (
          <label className="od-wishlist__toggle">
            <input
              type="checkbox"
              checked={showAll}
              onChange={(event) => setShowAll(event.target.checked)}
            />
            Show everyone’s requests
          </label>
        ) : null}

        {actionError ? (
          <PageStatus error={actionError} className="od-wishlist__action-error" />
        ) : null}

        <PageStatus
          loading={loading}
          error={error}
          errorMessage="Unable to load wishlist."
          loadingMessage="Loading requests…"
          onRetry={reload}
        />

        {!error && requests && requests.length === 0 ? (
          <p className="od-wishlist__empty">
            {useNewChrome
              ? 'No requests yet. Use Request a title above and your librarians will take a look.'
              : 'No requests yet. Add a title above and your librarians will take a look.'}
          </p>
        ) : null}

        {!error && requests && requests.length > 0 ? (
          <section aria-labelledby="wishlist-requests-heading">
            <div className="od-wishlist__section-head">
              <h2 id="wishlist-requests-heading">Requests</h2>
              <span className="od-wishlist__count">{requests.length}</span>
            </div>
            <ul className="od-wishlist__list">
              {requests.map((item: any) => (
                <li key={item.id} className="od-wishlist__row" data-request-id={item.id}>
                  <article>
                    <div className="od-wishlist__row-head">
                      <strong>{item.title}</strong>
                      <span className="od-wishlist__status" data-status={item.status}>
                        {item.status}
                      </span>
                      {item.created_at ? (
                        <time dateTime={item.created_at}>{formatLocaleDate(item.created_at)}</time>
                      ) : null}
                    </div>
                    {item.notes ? <p className="od-wishlist__notes">{item.notes}</p> : null}
                    {item.linked_game_uuid ? (
                      <a href={`/game_details/${item.linked_game_uuid}`}>Open game</a>
                    ) : null}
                    <div className="od-wishlist__actions">
                      {isLibrarian
                        ? RESOLVE_ACTIONS.map((action) => (
                            <button
                              key={action.status}
                              type="button"
                              className="od-cbtn"
                              disabled={busyId === item.id}
                              onClick={() => handleResolve(item.id, action.status)}
                            >
                              {action.label}
                            </button>
                          ))
                        : null}
                      {isLibrarian || item.status === 'pending' ? (
                        <button
                          type="button"
                          className="od-cbtn od-cbtn--danger"
                          disabled={busyId === item.id}
                          onClick={() => handleCancel(item.id)}
                        >
                          Cancel
                        </button>
                      ) : null}
                    </div>
                  </article>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </>
  )
}
