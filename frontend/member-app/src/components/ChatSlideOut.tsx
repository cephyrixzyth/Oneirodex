import { useEffect, useId, useRef, useState } from 'react'
import { ChatPanel } from './ChatPanel'
import {
  CLOSE_CHAT_EVENT,
  OPEN_CHAT_EVENT,
  openChatPopoutWindow,
  readChatPanelOpen,
  requestCloseChatPanel,
  requestOpenChatPanel,
  writeChatPanelOpen,
} from '../hooks/chatPanelApi'
import './ChatSlideOut.css'

/**
 * Left slide-out chat chrome — dismissible, reopen from launcher / More / Cmd+K / /chat deep-link.
 * TopNav stays available; panel sits under --od-topnav-offset. Expand widens to a full room.
 */
export function ChatSlideOut({
  defaultOpen,
  open: openProp,
  onOpenChange,
  canCreateRooms = true,
  viewer = {},
  hideLauncher = false,
}: LooseProps) {
  const controlled = typeof openProp === 'boolean'
  const [uncontrolledOpen, setUncontrolledOpen] = useState(() => {
    if (typeof defaultOpen === 'boolean') return defaultOpen
    return readChatPanelOpen(false)
  })
  const open = controlled ? openProp : uncontrolledOpen
  const [channelId, setChannelId] = useState<any>(null)
  const [expanded, setExpanded] = useState(false)
  const titleId = useId()

  function setOpen(next: any) {
    const value = typeof next === 'function' ? next(open) : next
    if (!controlled) setUncontrolledOpen(value)
    onOpenChange?.(value)
    if (!value) setExpanded(false)
  }
  // Window listeners below are registered once; they call the latest setOpen.
  const setOpenRef = useRef(setOpen)
  setOpenRef.current = setOpen

  useEffect(() => {
    if (controlled) return undefined
    writeChatPanelOpen(open)
  }, [open, controlled])

  useEffect(() => {
    function onOpenRequest(event: any) {
      const detail = event?.detail || {}
      if (detail.channelId != null) setChannelId(detail.channelId)
      if (detail.expanded) setExpanded(true)
      setOpenRef.current(true)
    }
    function onCloseRequest() {
      setOpenRef.current(false)
    }
    window.addEventListener(OPEN_CHAT_EVENT, onOpenRequest)
    window.addEventListener(CLOSE_CHAT_EVENT, onCloseRequest)
    return () => {
      window.removeEventListener(OPEN_CHAT_EVENT, onOpenRequest)
      window.removeEventListener(CLOSE_CHAT_EVENT, onCloseRequest)
    }
  }, [])

  useEffect(() => {
    if (!open) return undefined
    function onKey(event: any) {
      if (event.key === 'Escape') {
        if (event.target?.closest?.('input, textarea, select, [contenteditable]')) return
        event.preventDefault()
        setOpenRef.current(false)
        requestCloseChatPanel()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  function handleClose() {
    setOpen(false)
    requestCloseChatPanel()
  }

  function handleOpen() {
    setOpen(true)
    requestOpenChatPanel()
  }

  return (
    <>
      {!hideLauncher && !open ? (
        <button
          type="button"
          className="od-chat-slide__launcher"
          onClick={handleOpen}
          title="Open chat"
          aria-label="Open chat"
        >
          Chat
        </button>
      ) : null}

      {open ? (
        <>
          <button
            type="button"
            className="od-chat-slide__scrim"
            aria-label="Dismiss chat"
            onClick={handleClose}
          />
          <aside
            className={`od-chat-slide od-glass-panel is-open${expanded ? ' is-expanded' : ''}`}
            role="dialog"
            aria-modal="false"
            aria-labelledby={titleId}
          >
            <header className="od-chat-slide__header">
              <div>
                <h2 id={titleId} className="od-chat-slide__title">
                  Chat
                </h2>
                <p className="od-chat-slide__sub">
                  {expanded
                    ? 'Full household room — channels, thread, voice'
                    : 'Household rooms & DMs'}
                </p>
              </div>
              <div className="od-chat-slide__header-actions">
                <button
                  type="button"
                  className="od-chat-slide__expand"
                  aria-pressed={expanded}
                  onClick={() => setExpanded((v) => !v)}
                >
                  {expanded ? 'Compact' : 'Expand'}
                </button>
                {/* Pop out (GT-B17 · UID-010). Friends has had this since the
                    social wave; chat never did, so a conversation meant keeping
                    a panel over the library. */}
                <button
                  type="button"
                  className="od-chat-slide__expand"
                  title="Open chat in its own window"
                  onClick={() => openChatPopoutWindow(channelId)}
                >
                  Pop out
                </button>
                <button
                  type="button"
                  className="od-chat-slide__close"
                  aria-label="Hide chat"
                  onClick={handleClose}
                >
                  ×
                </button>
              </div>
            </header>
            <ChatPanel
              compact
              expanded={expanded}
              initialChannelId={channelId}
              canCreateRooms={canCreateRooms}
              viewer={viewer}
              onClose={handleClose}
            />
          </aside>
        </>
      ) : null}
    </>
  )
}
