import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react'
import { useNavigate } from 'react-router-dom'

import { buildAdminCommands, filterAdminCommands } from './adminCommands'
import { AdminLink } from './AdminLink'
import './AdminCommandPalette.css'

/**
 * ⌘K / Ctrl+K destination search for the admin shell (GT-A7).
 *
 * Hand-rolled rather than built on cmdk, which the member app uses. admin-app's
 * dependencies are react, react-dom and react-router-dom only, and a keyboard
 * list this small is not worth a new package plus its bundle weight — the whole
 * behaviour is under a hundred lines and stays in our control.
 *
 * Admin destinations stay inside the React shell through the shared AdminLink.
 */
export default function AdminCommandPalette() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const listRef = useRef<HTMLUListElement | null>(null)

  const commands = useMemo(() => buildAdminCommands(), [])
  const results = useMemo(() => filterAdminCommands(commands, query), [commands, query])

  const close = useCallback(() => {
    setOpen(false)
    setQuery('')
    setActive(0)
  }, [])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setOpen((wasOpen) => !wasOpen)
        return
      }
      if (event.key === 'Escape' && open) {
        event.preventDefault()
        close()
      }
    }
    // The top-bar Search button opens it too — the shortcut alone would be
    // invisible to anyone who has not been told it exists.
    function onOpenRequest() {
      setOpen(true)
    }

    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('od-admin-palette:open', onOpenRequest)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('od-admin-palette:open', onOpenRequest)
    }
  }, [open, close])

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  // Keep the highlighted row in view when arrowing past the fold.
  useEffect(() => {
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [active])

  function onInputKeyDown(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActive((i) => Math.min(i + 1, results.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((i) => Math.max(i - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const target = results[active]
      if (target) {
        close()
        navigate(target.href)
      }
    }
  }

  if (!open) return null

  return (
    <div
      className="od-admin-palette__scrim"
      role="presentation"
      onClick={(event) => {
        if (event.target === event.currentTarget) close()
      }}
    >
      <div className="od-admin-palette" role="dialog" aria-modal="true" aria-label="Search admin">
        <input
          ref={inputRef}
          className="od-admin-palette__input"
          type="text"
          placeholder="Search admin — pages, settings, integrations"
          aria-label="Search admin"
          value={query}
          onChange={(event) => {
            setQuery(event.target.value)
            setActive(0)
          }}
          onKeyDown={onInputKeyDown}
        />

        <ul className="od-admin-palette__list" ref={listRef} role="listbox" aria-label="Results">
          {results.length === 0 && (
            <li className="od-admin-palette__empty">No matching admin page.</li>
          )}
          {results.slice(0, 60).map((command, index) => (
            <li key={command.id}>
              <AdminLink
                className="od-admin-palette__row"
                to={command.href}
                role="option"
                aria-selected={index === active}
                data-active={index === active}
                onMouseEnter={() => setActive(index)}
              >
                <span className="od-admin-palette__label">{command.label}</span>
                <span className="od-admin-palette__section">{command.section}</span>
              </AdminLink>
            </li>
          ))}
        </ul>

        <div className="od-admin-palette__hint">
          <kbd>↑</kbd> <kbd>↓</kbd> to move · <kbd>Enter</kbd> to open · <kbd>Esc</kbd> to close
        </div>
      </div>
    </div>
  )
}
