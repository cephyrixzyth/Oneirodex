import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
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
  onDismiss,
}: {
  hidden: string[]
  labelFor: (id: string) => string
  onAdd: (id: string) => void
  open: boolean
  onToggle: () => void
  onDismiss: () => void
}) {
  const panelId = useId()
  const rootRef = useRef<HTMLSpanElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLUListElement | null>(null)
  const [menuPosition, setMenuPosition] = useState<{ top: number; left: number } | null>(null)

  useLayoutEffect(() => {
    if (!open) {
      setMenuPosition(null)
      return undefined
    }
    function updatePosition() {
      const rect = triggerRef.current?.getBoundingClientRect()
      if (!rect) return
      const menuWidth = 192
      setMenuPosition({
        top: rect.bottom + 5,
        left: Math.max(8, Math.min(rect.left, window.innerWidth - menuWidth - 8)),
      })
    }
    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    function isInside(event: Event) {
      const target = event.target as Node | null
      return Boolean(
        target && (rootRef.current?.contains(target) || menuRef.current?.contains(target)),
      )
    }
    function onPointerDown(event: PointerEvent) {
      if (!isInside(event)) onDismiss()
    }
    function onKeyDown(event: KeyboardEvent) {
      const activeElement = document.activeElement
      const focusInside = Boolean(
        activeElement &&
        (rootRef.current?.contains(activeElement) || menuRef.current?.contains(activeElement)),
      )
      if (event.key !== 'Escape' || !focusInside) return
      event.preventDefault()
      onDismiss()
      triggerRef.current?.focus()
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [onDismiss, open])

  return (
    <span className="od-dash__add" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="od-cbtn"
        aria-expanded={open}
        aria-controls={open && hidden.length ? panelId : undefined}
        disabled={hidden.length === 0}
        title={hidden.length ? 'Add a widget to the board' : 'Every widget is already on the board'}
        onClick={onToggle}
        onKeyDown={(event) => {
          if (event.key === 'Tab' && !event.shiftKey && open && hidden.length) {
            event.preventDefault()
            menuRef.current?.querySelector('button')?.focus()
          }
        }}
      >
        Add widget{hidden.length ? ` (${hidden.length})` : ''}
      </button>
      {open && hidden.length
        ? menuPosition
          ? createPortal(
              <ul
                ref={menuRef}
                className="od-dash__add-menu od-menu-surface"
                id={panelId}
                role="group"
                aria-label="Widgets to add"
                style={menuPosition}
              >
                {hidden.map((id) => (
                  <li key={id}>
                    <button
                      type="button"
                      className="od-dash__add-item od-menu-item"
                      onClick={() => onAdd(id)}
                    >
                      {labelFor(id)}
                    </button>
                  </li>
                ))}
              </ul>,
              document.querySelector('.od-topbar') ?? document.body,
            )
          : null
        : null}
    </span>
  )
}
