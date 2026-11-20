import { useState } from 'react'
import { Button } from '@oneirodex/ui'
import {
  activateModProfile,
  createModProfile,
  deleteModProfile,
  exportModProfile,
  importModProfile,
  type ModPack,
  type ModProfileImportResult,
} from '../api/mods'

/**
 * Named mod sets on one game (INSP-37).
 *
 * Activate is the one-click enable set — the profile's rows on, the rest off —
 * which is exactly what the companion's next *Apply mods* stages. The export
 * code (`od-mod:…`) carries names, versions, loaders and source pages, never a
 * file; importing on another game matches what that game already tracks and
 * lists the rest as missing instead of inventing rows.
 */
export function ModProfiles({
  gameUuid,
  pack,
  canEdit,
  onChanged,
  onError,
}: {
  gameUuid: string
  pack: ModPack
  canEdit: boolean
  onChanged: () => Promise<void> | void
  onError: (message: string) => void
}) {
  const [reviewId, setReviewId] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const [imported, setImported] = useState<ModProfileImportResult | null>(null)

  const review = pack.profiles.find((profile) => profile.id === reviewId)
  const selected = new Set(review?.mod_ids || [])
  const changes = pack.mods.filter((mod) => Boolean(mod.enabled) !== selected.has(mod.id))
  const missing = [
    ...(review?.unresolved || []),
    ...(review?.requirements || [])
      .filter((expected) => {
        const local = pack.mods.find((mod) => mod.id === expected.id)
        return (
          !local ||
          (expected.requires &&
            (expected.requires.length !== (local.requires?.length || 0) ||
              expected.requires.some((id) => !local.requires?.includes(id)))) ||
          (['version', 'loader', 'source_url'] as const).some(
            (key) => expected[key] && expected[key] !== local[key],
          )
        )
      })
      .map((expected) => expected.id),
  ]
  const expectedOrder = review?.import_order || []
  const orderedIds = new Set(expectedOrder)
  const actualOrder = pack.mods.filter((mod) => orderedIds.has(mod.id)).map((mod) => mod.id)
  const changedOrder = expectedOrder.some((id, index) => id !== actualOrder[index])
  const conflicts = pack.mods.filter(
    (mod) =>
      selected.has(mod.id) &&
      ((!['', 'none', 'manual'].includes(mod.loader || '') &&
        !['', 'none', 'manual'].includes(pack.default_loader) &&
        mod.loader !== pack.default_loader) ||
        mod.requires?.some((id) => !selected.has(id))),
  )
  const active = pack.profiles.find((p) => p.id === pack.active_profile) || null
  if (!canEdit && pack.profiles.length === 0) return null

  async function run(key: string, work: () => Promise<unknown>, fallback: string) {
    setCopied(null)
    setBusy(key)
    try {
      await work()
      await onChanged()
    } catch (err) {
      onError(err instanceof Error ? err.message : fallback)
    } finally {
      setBusy(null)
    }
  }

  async function copyCode(profileId: string) {
    setCopied(null)
    setBusy(`export:${profileId}`)
    try {
      const text = await exportModProfile(gameUuid, profileId)
      try {
        await navigator.clipboard.writeText(text)
        setCopied(profileId)
      } catch {
        // Clipboard can be blocked; fall back to showing the code in the import box.
        setCode(text)
      }
    } catch (err) {
      onError(err instanceof Error ? err.message : 'Could not export the profile')
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="od-mods__profiles">
      <h3 className="od-mods__form-title">
        Profiles
        {active ? <span className="od-mods__meta"> · active: {active.name}</span> : null}
      </h3>
      {pack.profiles.length === 0 ? (
        <p className="od-mods__muted">
          No profiles yet. Save the enabled set as one to switch between setups.
        </p>
      ) : (
        <ul className="od-mods__profile-list">
          {pack.profiles.map((profile) => (
            <li
              key={profile.id}
              className="od-mods__profile"
              data-active={profile.id === pack.active_profile}
            >
              <span className="od-mods__name">{profile.name}</span>
              <span className="od-mods__meta">
                {profile.mod_ids.length} mod{profile.mod_ids.length === 1 ? '' : 's'}
              </span>
              <span className="od-mods__actions">
                {canEdit ? (
                  <Button
                    type="button"
                    size="sm"
                    variant={profile.id === pack.active_profile ? 'ghost' : 'default'}
                    disabled={busy !== null}
                    onClick={() => setReviewId(profile.id)}
                  >
                    Review changes
                  </Button>
                ) : null}
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={busy !== null}
                  onClick={() => void copyCode(profile.id)}
                >
                  {copied === profile.id ? 'Copied' : 'Copy code'}
                </Button>
                {canEdit ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    disabled={busy !== null}
                    onClick={() =>
                      void run(
                        `delete:${profile.id}`,
                        () => deleteModProfile(gameUuid, profile.id),
                        'Could not remove the profile',
                      )
                    }
                  >
                    Remove
                  </Button>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      )}

      {review && canEdit && (
        <section aria-label="Profile changes">
          <h4>{review.name}</h4>
          <p>{changes.length ? 'Changes to enabled mods' : 'No changes to enabled mods'}</p>
          <ul>
            {changes.map((mod) => (
              <li key={mod.id}>
                {selected.has(mod.id) ? 'Enable' : 'Disable'} {mod.name} {mod.version}
              </li>
            ))}
          </ul>
          {missing.length > 0 && <p role="alert">Resolve and import again: {missing.join(', ')}</p>}
          {conflicts.length > 0 && (
            <p role="alert">
              Resolve loader or dependency conflicts for{' '}
              {conflicts.map((mod) => mod.name).join(', ')}.
            </p>
          )}
          {changedOrder && (
            <p role="alert">
              Restore the shared load order:{' '}
              {expectedOrder
                .map((id) => pack.mods.find((mod) => mod.id === id)?.name || id)
                .join(' → ')}
            </p>
          )}
          <Button onClick={() => setReviewId(null)}>Cancel</Button>
          <Button
            variant="primary"
            disabled={!!busy || !!missing.length || !!conflicts.length || changedOrder}
            onClick={() =>
              void run(
                'activate:' + review.id,
                async () => {
                  await activateModProfile(gameUuid, review.id)
                  setReviewId(null)
                },
                'Could not activate the profile',
              )
            }
          >
            Activate profile
          </Button>
        </section>
      )}
      {!canEdit && code ? (
        <label>
          Profile code
          <textarea readOnly value={code} onFocus={(event) => event.currentTarget.select()} />
        </label>
      ) : null}

      {canEdit ? (
        <>
          <form
            className="od-mods__profile-form"
            onSubmit={(event) => {
              event.preventDefault()
              if (!name.trim()) return
              void run(
                'create',
                () => createModProfile(gameUuid, name.trim()),
                'Could not save the profile',
              ).then(() => setName(''))
            }}
          >
            <label>
              Save the enabled set as
              <input
                type="text"
                value={name}
                maxLength={120}
                placeholder="e.g. Vanilla+"
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <Button type="submit" size="sm" disabled={busy !== null || !name.trim()}>
              Save profile
            </Button>
          </form>

          <form
            className="od-mods__profile-form"
            onSubmit={(event) => {
              event.preventDefault()
              if (!code.trim()) return
              void run(
                'import',
                async () => {
                  setImported(await importModProfile(gameUuid, code))
                  setCode('')
                },
                'Could not import the profile',
              )
            }}
          >
            <label>
              Import a profile code
              <input
                type="text"
                value={code}
                placeholder="od-mod:…"
                onChange={(event) => setCode(event.target.value)}
              />
            </label>
            <Button
              type="submit"
              size="sm"
              variant="ghost"
              disabled={busy !== null || !code.trim()}
            >
              Import
            </Button>
          </form>
          {imported ? (
            <p className="od-mods__muted" role="note">
              Imported <strong>{imported.profile?.name}</strong>: {imported.matched} already tracked
              here
              {imported.missing.length
                ? `, ${imported.missing.length} not tracked — add ${imported.missing
                    .map((m) => m.name)
                    .join(', ')} first, then import again.`
                : '.'}
            </p>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
