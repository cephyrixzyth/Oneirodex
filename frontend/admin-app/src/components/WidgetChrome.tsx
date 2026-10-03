import { SIZE_PRESET_LABELS, type SizePreset } from './dashboardLayout'

const PRESETS: SizePreset[] = ['small', 'medium', 'large', 'full']
const PRESET_SHORT: Record<SizePreset, string> = {
  small: 'S',
  medium: 'M',
  large: 'L',
  full: 'Full',
}

/**
 * Per-widget toolbar: pin (lock position and size), size presets, hide.
 * Shown on hover and keyboard focus so it does not add chrome to a quiet board.
 */
export function WidgetChrome({
  label,
  pinned,
  onTogglePin,
  onPreset,
  onHide,
}: {
  label: string
  pinned: boolean
  onTogglePin: () => void
  onPreset: (preset: SizePreset) => void
  onHide: () => void
}) {
  return (
    <div className="od-dash__tools" role="toolbar" aria-label={`${label} controls`}>
      {PRESETS.map((preset) => (
        <button
          key={preset}
          type="button"
          className="od-dash__tool"
          disabled={pinned}
          title={`${SIZE_PRESET_LABELS[preset]} width`}
          aria-label={`${label}: ${SIZE_PRESET_LABELS[preset]} width`}
          onClick={() => onPreset(preset)}
        >
          {PRESET_SHORT[preset]}
        </button>
      ))}
      <button
        type="button"
        className="od-dash__tool"
        aria-pressed={pinned}
        title={pinned ? 'Unpin: allow move and resize' : 'Pin: lock position and size'}
        aria-label={`${pinned ? 'Unpin' : 'Pin'} ${label}`}
        onClick={onTogglePin}
      >
        {pinned ? '📌' : '📍'}
      </button>
      <button
        type="button"
        className="od-dash__tool"
        disabled={pinned}
        title="Hide this widget"
        aria-label={`Hide ${label}`}
        onClick={onHide}
      >
        ×
      </button>
    </div>
  )
}

/** "Add widget" list in the page bar: one row per hidden widget. */
export function AddWidgetMenu({
  hidden,
  labelFor,
  onAdd,
  open,
  onToggle,
}: {
  hidden: string[]
  labelFor: (id: string) => string
  onAdd: (id: string) => void
  open: boolean
  onToggle: () => void
}) {
  return (
    <span className="od-dash__add">
      <button
        type="button"
        className="od-cbtn"
        aria-expanded={open}
        aria-haspopup="menu"
        disabled={hidden.length === 0}
        title={hidden.length ? 'Add a widget to the board' : 'Every widget is already on the board'}
        onClick={onToggle}
      >
        Add widget{hidden.length ? ` (${hidden.length})` : ''}
      </button>
      {open && hidden.length ? (
        <ul className="od-dash__add-menu" role="menu">
          {hidden.map((id) => (
            <li key={id} role="none">
              <button
                type="button"
                role="menuitem"
                className="od-dash__add-item"
                onClick={() => onAdd(id)}
              >
                {labelFor(id)}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </span>
  )
}
