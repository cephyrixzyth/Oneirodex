import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { confirmAction, useResource, useShellConfig } from '@oneirodex/ui'
import { ContextBar, Popover } from '../chrome/ContextBar'
import { createCollection, deleteCollection, fetchCollections } from '../api/collections'
import { PageStatus } from '../components/PageStatus'
import { SmartCollections } from '../components/SmartCollections'
import './Collections.css'

// Stable identity so the optimistic create / delete writes below target the
// same cache entry `useResource` reads.
const COLLECTIONS_QUERY_KEY = ['collections']

function itemCountLabel(collection: any) {
  const count = Number(collection.item_count)
  if (!Number.isFinite(count)) {
    return null
  }
  return count === 1 ? '1 game' : `${count} games`
}

export function CollectionsPage() {
  const shellConfig = useShellConfig()
  const useNewChrome = Boolean(shellConfig.enableNewChrome)
  const queryClient = useQueryClient()
  const {
    data: collections,
    loading,
    error,
    reload,
  } = useResource(COLLECTIONS_QUERY_KEY, ({ signal }) =>
    fetchCollections({ signal }).then((data) =>
      Array.isArray(data.collections) ? data.collections : [],
    ),
  )
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [isPublic, setIsPublic] = useState(true)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<any>(null)
  const [deletingUuid, setDeletingUuid] = useState<any>(null)

  async function handleCreate(event: any) {
    event.preventDefault()
    const trimmedName = name.trim()
    if (creating) {
      return
    }
    if (!trimmedName) {
      setCreateError(new Error('Enter a shelf name before creating it.'))
      return
    }

    setCreating(true)
    setCreateError(null)
    try {
      const created = await createCollection({
        name: trimmedName,
        description: description.trim(),
        isPublic,
      })
      queryClient.setQueryData(COLLECTIONS_QUERY_KEY, (current: LooseProps[] | undefined) => [
        created,
        ...(current || []),
      ])
      setName('')
      setDescription('')
      setIsPublic(true)
    } catch (submitError: any) {
      setCreateError(submitError)
    } finally {
      setCreating(false)
    }
  }

  async function handleDelete(collection: any) {
    if (!collection?.can_edit || collection.is_system || deletingUuid) {
      return
    }
    const confirmed = await confirmAction({
      title: `Delete “${collection.name}”?`,
      body: 'The games stay in your catalog — only the collection goes.',
      confirmLabel: 'Delete collection',
      cancelLabel: 'Keep it',
    })
    if (!confirmed) {
      return
    }
    setDeletingUuid(collection.uuid)
    try {
      await deleteCollection(collection.uuid)
      queryClient.setQueryData(COLLECTIONS_QUERY_KEY, (current: LooseProps[] | undefined) =>
        (current || []).filter((row) => row.uuid !== collection.uuid),
      )
    } catch (deleteError: any) {
      window.alert(deleteError.message || 'Unable to delete that collection.')
    } finally {
      setDeletingUuid(null)
    }
  }

  return (
    <>
      {useNewChrome ? (
        <ContextBar
          summary={collections ? `${collections.length} shelves` : null}
          actions={
            /* "New shelf", with the same glyph the rail uses for Collections.
               The page calls them shelves in its own copy and its own count, so
               a button labelled "New collection" was the only place the word
               changed — which is why there appeared to be "no way to make
               shelves". A Collection *is* a shelf; see models.Collection. */
            /* Quiet bar chrome: no primary fill, no icon. Wash only while the
               popover is open (aria-expanded) — see od-appbar contextbar rules. */
            <Popover label="New shelf">
              <form className="od-collections__form" onSubmit={handleCreate}>
                <label className="od-collections__field">
                  Name
                  <input
                    type="text"
                    maxLength={120}
                    required
                    placeholder="Cozy co-op nights"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                  />
                </label>
                <label className="od-collections__field">
                  Description
                  <input
                    type="text"
                    maxLength={400}
                    placeholder="Optional"
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </label>
                <label className="od-collections__check">
                  <input
                    type="checkbox"
                    checked={isPublic}
                    onChange={(event) => setIsPublic(event.target.checked)}
                  />
                  Public
                </label>
                <button type="submit" className="od-cbtn od-cbtn--primary" disabled={creating}>
                  {creating ? 'Creating…' : 'Create shelf'}
                </button>
                {createError ? (
                  <PageStatus
                    error={createError}
                    errorMessage={createError.message || 'Unable to create collection.'}
                    className="od-collections__error"
                  />
                ) : null}
              </form>
            </Popover>
          }
        />
      ) : null}
      <div className="od-more-page od-collections">
        {useNewChrome ? null : (
          <>
            <div className="od-page-header">
              <h1>Collections</h1>
            </div>
            <p className="od-more-page__lede">
              Curated shelves you and others share across the library.
            </p>

            <form className="od-collections__form" onSubmit={handleCreate}>
              <label className="od-collections__field">
                Name
                <input
                  type="text"
                  maxLength={120}
                  required
                  placeholder="Cozy co-op nights"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                />
              </label>
              <label className="od-collections__field">
                Description
                <input
                  type="text"
                  maxLength={400}
                  placeholder="Optional"
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                />
              </label>
              <label className="od-collections__check">
                <input
                  type="checkbox"
                  checked={isPublic}
                  onChange={(event) => setIsPublic(event.target.checked)}
                />
                Public
              </label>
              <button type="submit" className="od-cbtn od-cbtn--primary" disabled={creating}>
                {creating ? 'Creating…' : 'Create shelf'}
              </button>
              {createError ? (
                <PageStatus
                  error={createError}
                  errorMessage={createError.message || 'Unable to create collection.'}
                  className="od-collections__error"
                />
              ) : null}
            </form>
          </>
        )}

        {/* INSP-29 — saved filters that asked to be shelves. Renders nothing
            when there are none, so the page is unchanged until a member makes
            one. */}
        <SmartCollections />

        <PageStatus
          loading={loading}
          error={error}
          errorMessage="Unable to load collections."
          loadingMessage="Loading shelves…"
          onRetry={reload}
        />

        {!error && collections && collections.length === 0 ? (
          <p>
            {useNewChrome
              ? 'No collections yet. Create your first one from New shelf above.'
              : 'No collections yet. Create your first shelf with the form above.'}
          </p>
        ) : null}

        {!error && collections && collections.length > 0 ? (
          <ul className="od-collections__list">
            {collections.map((collection: any) => {
              const countLabel = itemCountLabel(collection)
              return (
                <li key={collection.uuid} className="od-collections__row">
                  <Link className="od-collections__card" to={`/collections/${collection.uuid}`}>
                    <strong>{collection.name}</strong>
                    <span className="od-collections__card-desc">
                      {collection.description || 'No description'}
                    </span>
                    <span className="od-collections__meta">
                      {collection.is_public ? 'Public' : 'Private'}
                      {collection.is_system ? ' · System' : ''}
                      {countLabel ? ` · ${countLabel}` : ''}
                    </span>
                  </Link>
                  {collection.can_edit && !collection.is_system ? (
                    <button
                      type="button"
                      className="od-collections__delete"
                      disabled={deletingUuid === collection.uuid}
                      onClick={() => handleDelete(collection)}
                    >
                      {deletingUuid === collection.uuid ? 'Deleting…' : 'Delete'}
                    </button>
                  ) : null}
                </li>
              )
            })}
          </ul>
        ) : null}
      </div>
    </>
  )
}
