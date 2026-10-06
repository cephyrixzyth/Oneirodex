import { useCallback, useEffect, useState } from 'react'
import { Button } from '@oneirodex/ui'
import { safeHttpUrl } from '../utils/safeUrl'
import {
  createMod,
  deleteMod,
  fetchMods,
  setDefaultLoader,
  updateMod,
  type ModDraft,
  type ModHit,
  type ModPack,
} from '../api/mods'
import { ModCatalogDrawer } from './ModCatalogDrawer'
import { ModProfiles } from './ModProfiles'
import { PageStatus } from './PageStatus'
import './ModsPanel.css'

const EMPTY_DRAFT: ModDraft = { name: '', version: '', source_url: '', notes: '', loader: '' }

/**
 * Tracked mods for one game (MOD-3 list, INSP-36 loader, INSP-22 browse).
 *
 * Everyone sees the list when there is one; a librarian (`canEdit`) also gets
 * the pack's default loader, an add form, and the catalogue drawer. The list
 * is metadata: a name, a version, the loader it needs, a source URL the
 * companion may stage. Nothing here installs a mod or a loader.
 */
export function ModsPanel({ gameUuid, canEdit = false }: { gameUuid: string; canEdit?: boolean }) {
  const [pack, setPack] = useState<ModPack | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState<ModDraft>(EMPTY_DRAFT)
  const [saving, setSaving] = useState(false)
  const [browsing, setBrowsing] = useState(false)

  const load = useCallback(async () => {
    if (!gameUuid) {
      setLoading(false)
      return
    }
    setLoading(true)
    setError('')
    try {
      setPack(await fetchMods(gameUuid))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load mods')
      setPack(null)
    } finally {
      setLoading(false)
    }
  }, [gameUuid])

  useEffect(() => {
    void load()
  }, [load])

  // Tracking off server-side, or nothing to show and nobody who could add: stay out of the page.
  if (!loading && (!pack || pack.enabled === false)) return null
  if (!loading && pack && pack.mods.length === 0 && !canEdit) return null

  const mods = pack?.mods ?? []
  const loaders = pack?.loaders ?? []
  const defaultLoader = pack?.default_loader ?? ''

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (!draft.name.trim()) return
    setSaving(true)
    setError('')
    try {
      await createMod(gameUuid, { ...draft, name: draft.name.trim() })
      setDraft({ ...EMPTY_DRAFT, loader: draft.loader })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add the mod')
    } finally {
      setSaving(false)
    }
  }

  function draftFromHit(hit: ModHit, requires: string[] = []): ModDraft {
    return {
      name: hit.name,
      version: hit.version,
      source_url: hit.url,
      loader: hit.loader,
      notes: hit.summary ? `${hit.summary} (${hit.source})` : `from ${hit.source}`,
      requires,
    }
  }

  /** One action (INSP-38): the dependencies first, then the hit pointing at them. */
  async function addFromCatalog(hit: ModHit, dependencies: ModHit[] = []) {
    setError('')
    try {
      const requires: string[] = []
      for (const dep of dependencies) {
        const row = await createMod(gameUuid, draftFromHit(dep))
        if (row?.id) requires.push(row.id)
      }
      await createMod(gameUuid, draftFromHit(hit, requires))
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add the mod')
    }
  }

  /** INSP-39: the librarian saw a newer version on the registry and says the row is on it now. */
  async function noteUpdate(hit: ModHit) {
    if (!hit.tracked_id || !hit.update_available) return
    setError('')
    try {
      await updateMod(gameUuid, hit.tracked_id, {
        version: hit.update_available,
        latest_seen_version: hit.update_available,
      })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update the mod')
    }
  }

  async function toggle(modId: string, enabled: boolean) {
    setError('')
    try {
      await updateMod(gameUuid, modId, { enabled })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update the mod')
    }
  }

  async function remove(modId: string) {
    setError('')
    try {
      await deleteMod(gameUuid, modId)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not remove the mod')
    }
  }

  async function changeDefaultLoader(loader: string) {
    setError('')
    try {
      await setDefaultLoader(gameUuid, loader)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the loader')
    }
  }

  return (
    <section className="od-mods" aria-labelledby="od-mods-heading">
      <div className="od-mods__head">
        <h2 id="od-mods-heading">Mods</h2>
        {canEdit ? (
          <Button type="button" size="sm" pill onClick={() => setBrowsing(true)}>
            Browse catalogue
          </Button>
        ) : null}
      </div>
      <p className="od-mods__lede">
        A tracked list — name, version, the loader it needs, where it came from. The desktop
        companion can stage these URLs into a local install; nothing here installs a mod or a
        loader.
      </p>

      <PageStatus
        loading={loading}
        error={error}
        loadingMessage="Loading mods…"
        className="od-mods__status"
      />

      {pack && pack.loader_conflicts.length > 0 ? (
        <p className="od-mods__conflict" role="note">
          Loader mismatch: the pack is set to <strong>{pack.default_loader}</strong> but{' '}
          {pack.loader_conflicts.map((c) => `${c.name} (${c.loader})`).join(', ')}{' '}
          {pack.loader_conflicts.length === 1 ? 'needs' : 'need'} a different loader. The companion
          refuses to apply this set until the rows or the default agree.
        </p>
      ) : null}

      {canEdit && pack ? (
        <label className="od-mods__default">
          <span>Default loader for this game</span>
          <LoaderInput
            value={defaultLoader}
            loaders={loaders}
            listId="od-mods-loaders"
            onCommit={(value) => void changeDefaultLoader(value)}
          />
        </label>
      ) : null}

      {!loading && mods.length === 0 ? (
        <p className="od-mods__muted">
          No mods tracked for this title yet.
          {canEdit ? ' Add one below or browse a catalogue.' : ''}
        </p>
      ) : null}

      {mods.length > 0 ? (
        <ul className="od-mods__list">
          {mods.map((mod) => {
            const loader = mod.loader || defaultLoader
            return (
              <li
                key={mod.id}
                className="od-mods__item"
                data-enabled={mod.enabled ? 'true' : 'false'}
              >
                <div className="od-mods__row">
                  <strong className="od-mods__name">{mod.name}</strong>
                  {mod.version ? <span className="od-mods__meta">v{mod.version}</span> : null}
                  {loader ? (
                    <span
                      className="od-mods__loader"
                      title={mod.loader ? 'Loader on this row' : 'Pack default loader'}
                    >
                      {loader}
                    </span>
                  ) : null}
                  {!mod.enabled ? <span className="od-mods__meta">disabled</span> : null}
                  {mod.requires && mod.requires.length ? (
                    <span className="od-mods__meta">
                      needs{' '}
                      {mod.requires
                        .map((id) => mods.find((m) => m.id === id)?.name || id)
                        .join(', ')}
                    </span>
                  ) : null}
                </div>
                {mod.notes ? <p className="od-mods__notes">{mod.notes}</p> : null}
                <div className="od-mods__actions">
                  {safeHttpUrl(mod.source_url) ? (
                    <a
                      className="od-mods__link"
                      href={safeHttpUrl(mod.source_url) || undefined}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      Source
                    </a>
                  ) : null}
                  {canEdit ? (
                    <>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => void toggle(mod.id, !mod.enabled)}
                      >
                        {mod.enabled ? 'Disable' : 'Enable'}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => void remove(mod.id)}
                      >
                        Remove
                      </Button>
                    </>
                  ) : null}
                </div>
              </li>
            )
          })}
        </ul>
      ) : null}

      {pack && (mods.length > 0 || canEdit) ? (
        <ModProfiles
          gameUuid={gameUuid}
          pack={pack}
          canEdit={canEdit}
          onChanged={load}
          onError={setError}
        />
      ) : null}

      {canEdit ? (
        <form className="od-mods__form" onSubmit={submit}>
          <h3 className="od-mods__form-title">Add a mod</h3>
          <label>
            Name
            <input
              type="text"
              value={draft.name}
              maxLength={256}
              onChange={(event) => setDraft({ ...draft, name: event.target.value })}
              placeholder="e.g. Configuration Manager"
            />
          </label>
          <label>
            Version
            <input
              type="text"
              value={draft.version}
              maxLength={64}
              onChange={(event) => setDraft({ ...draft, version: event.target.value })}
            />
          </label>
          <label>
            Source URL
            <input
              type="url"
              value={draft.source_url}
              maxLength={2048}
              onChange={(event) => setDraft({ ...draft, source_url: event.target.value })}
              placeholder="Registry page or the archive you chose"
            />
          </label>
          <label>
            Loader
            <LoaderInput
              value={draft.loader || ''}
              loaders={loaders}
              listId="od-mods-loaders"
              onCommit={(value) => setDraft({ ...draft, loader: value })}
              live
            />
          </label>
          <label>
            Notes
            <input
              type="text"
              value={draft.notes}
              maxLength={4000}
              onChange={(event) => setDraft({ ...draft, notes: event.target.value })}
            />
          </label>
          <Button type="submit" variant="primary" disabled={saving || !draft.name.trim()}>
            {saving ? 'Saving…' : 'Add mod'}
          </Button>
        </form>
      ) : null}

      {canEdit ? (
        <ModCatalogDrawer
          gameUuid={gameUuid}
          open={browsing}
          onClose={() => setBrowsing(false)}
          onAdd={addFromCatalog}
          onNoteUpdate={noteUpdate}
        />
      ) : null}
    </section>
  )
}

/** A text input with the suggested loaders as a datalist — a select that still takes free text. */
function LoaderInput({
  value,
  loaders,
  listId,
  onCommit,
  live = false,
}: {
  value: string
  loaders: string[]
  listId: string
  onCommit: (value: string) => void
  live?: boolean
}) {
  const [text, setText] = useState(value)
  useEffect(() => setText(value), [value])
  return (
    <>
      <input
        type="text"
        list={listId}
        value={text}
        maxLength={64}
        placeholder="bepinex, smapi, fabric, none…"
        onChange={(event) => {
          setText(event.target.value)
          if (live) onCommit(event.target.value)
        }}
        onBlur={() => {
          if (!live && text !== value) onCommit(text)
        }}
      />
      <datalist id={listId}>
        {loaders.map((loader) => (
          <option key={loader} value={loader} />
        ))}
      </datalist>
    </>
  )
}
