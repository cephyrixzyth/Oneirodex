import { useEffect, useId, useRef, useState } from 'react'
import { groupLabel } from './librariesModel'
import type { LibraryRow } from './librariesModel'

/* GroupDialog moved out of LibrariesPanel (v11 cycle, H-D.2) — unchanged. */

export function GroupDialog({
  targets,
  existingNames,
  onClose,
  onSave,
  busy,
}: {
  targets: LibraryRow[]
  existingNames: string[]
  onClose?: () => void
  onSave: (name: string) => void
  busy?: boolean
}) {
  const titleId = useId()
  const listId = useId()
  const shared = targets.length
    ? targets.every((lib) => groupLabel(lib) === groupLabel(targets[0]))
      ? groupLabel(targets[0])
      : ''
    : ''
  const [name, setName] = useState(shared)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const anyGroupedTargets = targets.some((lib) => groupLabel(lib))

  useEffect(() => {
    inputRef.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose?.()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  if (!targets.length) return null

  const count = targets.length
  const heading = count === 1 ? `Group ${targets[0].name}` : `Group ${count} libraries`

  return (
    <div
      className="od-libraries-group"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={() => {
        if (!busy) onClose?.()
      }}
    >
      <div className="od-libraries-group__panel" onClick={(event) => event.stopPropagation()}>
        <h2 id={titleId} className="od-libraries-group__title">
          {heading}
        </h2>
        <p className="od-libraries-group__lede">
          Libraries that share a group name sit together. Clear the name to ungroup. The Group
          column only appears when at least one library is grouped.
        </p>
        <label className="od-libraries-group__field">
          <span>Group name</span>
          <input
            ref={inputRef}
            type="text"
            className="od-table__col-filter od-libraries-group__input"
            value={name}
            list={existingNames.length ? listId : undefined}
            maxLength={80}
            autoComplete="off"
            onChange={(event) => setName(event.target.value)}
            placeholder="e.g. Arcade cabinets"
          />
        </label>
        {existingNames.length ? (
          <datalist id={listId}>
            {existingNames.map((value) => (
              <option key={value} value={value} />
            ))}
          </datalist>
        ) : null}
        <div className="od-libraries-group__actions">
          <button type="button" className="od-cbtn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          {anyGroupedTargets ? (
            <button type="button" className="od-cbtn" disabled={busy} onClick={() => onSave('')}>
              Ungroup
            </button>
          ) : null}
          <button
            type="button"
            className="od-cbtn od-cbtn--primary"
            disabled={busy || !name.trim()}
            onClick={() => onSave(name)}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * Libraries list for the Jinja Libraries pane — DataTable with inline
 * typeahead filters, themed row actions, grouping, and multi-select batch
 * Scan/Edit/Delete/Group. Per-row and batch Edit open the shared edit modal
 * (stays on this page); the modal can still link out to the full editor.
 */
// `panelEl` is still passed by useLibrariesPanelMount; the panel has not read it
// since the DataTable cutover, and the prop stays so the mount contract does not move.
