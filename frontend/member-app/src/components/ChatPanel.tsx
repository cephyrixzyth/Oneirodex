import { useEffect, useId, useRef, useState } from 'react'
import { PageStatus } from './PageStatus'
import { VoiceLobby } from './VoiceLobby'
import {
  createChatChannel,
  fetchChatChannels,
  fetchChatEmoji,
  fetchChatMessages,
  openChatDm,
  postChatMessage,
  probeChatAttachmentUpload,
  searchChat,
  toggleChatReaction,
} from '../api/chat'
import { canArchiveChannel, canLeaveChannel, slugifyRoomName } from '../hooks/chatPanelApi'
import '../pages/ChatPage.css'

import { ChatComposer } from './chat/ChatComposer'
import { useAttachmentUpload, useRoomActions } from './chat/useChatActions'
import { ChatMessageList } from './chat/ChatMessageList'
import { ChatRoomsAside } from './chat/ChatRoomsAside'
import { ChatThreadHead } from './chat/ChatThreadHead'
import {
  FIXED_REACTION_EMOJIS,
  POLL_MS,
  ATTACH_HINT_UNAVAILABLE,
  ATTACH_HINT_CHILD,
  mergeById,
} from './chat/chatHelpers'

export function ChatPanel({
  compact = false,
  initialChannelId = null,
  canCreateRooms = true,
  viewer = {},
  onClose,
  onExpandToggle,
  expanded = false,
}: LooseProps) {
  const [channels, setChannels] = useState<any[]>([])
  const [channelsLoading, setChannelsLoading] = useState(true)
  const [activeId, setActiveId] = useState(initialChannelId)
  const [messages, setMessages] = useState<any[]>([])
  const [body, setBody] = useState('')
  const [dmName, setDmName] = useState('')
  const [searchQ, setSearchQ] = useState('')
  const [searchHits, setSearchHits] = useState<any[]>([])
  const [replyTo, setReplyTo] = useState<any>(null)
  const [error, setError] = useState<any>(null)
  const [msg, setMsg] = useState<any>(null)
  const [msgIsError, setMsgIsError] = useState(false)
  const [newRoomName, setNewRoomName] = useState('')
  const [creatingRoom, setCreatingRoom] = useState(false)
  const [showTools, setShowTools] = useState(false)
  const [showEmojiPicker, setShowEmojiPicker] = useState(false)
  const [pendingAttachments, setPendingAttachments] = useState<any[]>([])
  const [voiceOpen, setVoiceOpen] = useState(false)
  const [preferScreenshare, setPreferScreenshare] = useState(false)
  // Voice is scoped to the channel the member picked. Null = the household
  // lobby; the server refuses any room it cannot resolve to real membership.
  const [voiceChannel, setVoiceChannel] = useState<any>(null)
  const [reactionItems, setReactionItems] = useState(
    FIXED_REACTION_EMOJIS.map((emoji) => ({ emoji, label: emoji })),
  )
  const messagesRef = useRef<any[]>([])
  const listEndRef = useRef<any>(null)
  const composerRef = useRef<any>(null)
  const fileInputRef = useRef<any>(null)
  const emojiPickerId = useId()
  const viewerIsChild = String(viewer?.role || '').toLowerCase() === 'child'

  function showStatus(text: string | null, { isError = false }: { isError?: boolean } = {}) {
    setMsg(text)
    setMsgIsError(isError)
  }

  const { roomActionBusy, toggleMute, archiveActiveRoom, leaveActiveRoom } = useRoomActions({
    activeId,
    channels,
    setChannels,
    viewer,
    setMessages,
    setReplyTo,
    loadChannels,
    showStatus,
  })
  const { attachAvailable, setAttachAvailable, attachBusy, handleAttachFiles } =
    useAttachmentUpload({
      activeId,
      viewerIsChild,
      pendingAttachments,
      setPendingAttachments,
      showStatus,
    })

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  useEffect(() => {
    listEndRef.current?.scrollIntoView?.({ block: 'end' })
  }, [messages, activeId])

  useEffect(() => {
    if (initialChannelId != null) setActiveId(initialChannelId)
  }, [initialChannelId])

  useEffect(() => {
    setPendingAttachments([])
    setShowEmojiPicker(false)
    setReplyTo(null)
  }, [activeId])

  useEffect(() => {
    if (viewerIsChild) {
      setAttachAvailable(false)
      return undefined
    }
    if (!activeId || attachAvailable === false) return undefined
    let cancelled = false
    void probeChatAttachmentUpload(activeId).then((result) => {
      if (cancelled) return
      if (result === 'no') setAttachAvailable(false)
      else if (result === 'yes') setAttachAvailable(true)
    })
    return () => {
      cancelled = true
    }
  }, [activeId, attachAvailable, setAttachAvailable, viewerIsChild])

  async function loadEmoji() {
    try {
      const data = await fetchChatEmoji()
      if (!data) return
      const fixed = (Array.isArray(data.fixed) ? data.fixed : FIXED_REACTION_EMOJIS).map(
        (emoji: any) => ({
          emoji,
          label: emoji,
        }),
      )
      const custom = (Array.isArray(data.custom) ? data.custom : []).map((row: any) => ({
        emoji: row.emoji || `:${row.slug}:`,
        label: row.label || row.slug,
        url: row.url,
      }))
      setReactionItems([...fixed, ...custom])
    } catch {
      // Keep fixed set on failure.
    }
  }

  async function loadChannels() {
    const data = (await fetchChatChannels()) ?? {}
    const list = Array.isArray(data.channels) ? data.channels : []
    setChannels(list)
    setActiveId((prev: any) => {
      if (prev && list.some((c: any) => c.id === prev)) return prev
      if (initialChannelId && list.some((c: any) => c.id === initialChannelId))
        return initialChannelId
      return list.length ? list[0].id : null
    })
    return list
  }

  async function loadMessages(channelId: any, { sinceId }: LooseProps = {}) {
    if (!channelId) return
    const data = (await fetchChatMessages(channelId, { sinceId })) ?? {}
    const next = Array.isArray(data.messages) ? data.messages : []
    if (sinceId) {
      setMessages((prev) => mergeById(prev, next))
    } else {
      setMessages(next)
    }
  }

  // Load once on mount; the ref keeps that one call on the latest loadChannels.
  const loadChannelsRef = useRef(loadChannels)
  loadChannelsRef.current = loadChannels
  useEffect(() => {
    setChannelsLoading(true)
    loadChannelsRef
      .current()
      .catch(() => setError(true))
      .finally(() => setChannelsLoading(false))
    void loadEmoji()
  }, [])

  useEffect(() => {
    if (!activeId) return undefined

    let cancelled = false
    let timer = 0

    async function fullLoad() {
      try {
        await loadMessages(activeId)
      } catch {
        if (!cancelled) setError(true)
      }
    }

    async function pollIncremental() {
      if (document.visibilityState === 'hidden') return
      const last = messagesRef.current[messagesRef.current.length - 1]
      try {
        if (last?.id) {
          await loadMessages(activeId, { sinceId: last.id })
        } else {
          await loadMessages(activeId)
        }
      } catch {
        // Keep last good snapshot on poll failure.
      }
    }

    function onVisibility() {
      if (document.visibilityState === 'visible') {
        void pollIncremental()
      }
    }

    void fullLoad()
    timer = window.setInterval(() => {
      void pollIncremental()
    }, POLL_MS)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      cancelled = true
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [activeId])

  function insertEmoji(item: any) {
    const insert = item.url ? `:${item.label || item.emoji}:` : item.emoji
    const el = composerRef.current
    if (el && typeof el.selectionStart === 'number') {
      const start = el.selectionStart
      const end = el.selectionEnd
      const next = `${body.slice(0, start)}${insert}${body.slice(end)}`
      setBody(next)
      requestAnimationFrame(() => {
        el.focus()
        const pos = start + insert.length
        el.setSelectionRange(pos, pos)
      })
    } else {
      setBody((prev) => `${prev}${insert}`)
    }
    setShowEmojiPicker(false)
  }

  async function sendMessage(event: any) {
    event.preventDefault()
    if (!activeId) return
    const trimmed = body.trim()
    const attachmentIds = pendingAttachments.map((a) => a.id).filter((id) => id != null)
    if (!trimmed && !attachmentIds.length) return
    const payload: LooseProps = {
      body: trimmed,
      parent_message_id: replyTo?.id || undefined,
    }
    if (attachmentIds.length) payload.attachment_ids = attachmentIds
    const result = await postChatMessage(activeId, payload)
    if (!result.ok) {
      showStatus(result.error, { isError: true })
      return
    }
    setBody('')
    setReplyTo(null)
    setPendingAttachments([])
    setShowEmojiPicker(false)
    showStatus(null)
    await loadMessages(activeId)
  }

  async function openDm(event: any) {
    event.preventDefault()
    const username = dmName.trim()
    if (!username) return
    const result = await openChatDm({ username })
    if (!result.ok) {
      showStatus(result.error, { isError: true })
      return
    }
    setDmName('')
    await loadChannels()
    if (result.data?.channel?.id) setActiveId(result.data.channel.id)
  }

  async function createRoom(event: any) {
    event.preventDefault()
    const name = newRoomName.trim()
    if (!name) return
    const slug = slugifyRoomName(name)
    if (!slug) {
      showStatus('Room name needs letters or numbers', { isError: true })
      return
    }
    setCreatingRoom(true)
    showStatus(null)
    try {
      const result = await createChatChannel({ name, slug, is_child_safe: true })
      if (!result.ok) {
        showStatus(result.error, { isError: true })
        return
      }
      setNewRoomName('')
      await loadChannels()
      if (result.data?.channel?.id) setActiveId(result.data.channel.id)
    } finally {
      setCreatingRoom(false)
    }
  }

  async function runSearch(event: any) {
    event.preventDefault()
    const q = searchQ.trim()
    if (q.length < 2) {
      setSearchHits([])
      return
    }
    const result = await searchChat(q)
    if (!result.ok) {
      showStatus(result.error, { isError: true })
      return
    }
    setSearchHits(Array.isArray(result.data?.results) ? result.data.results : [])
  }

  async function toggleReaction(messageId: any, emoji: any) {
    const result = await toggleChatReaction(messageId, emoji)
    if (!result.ok) return
    const data = result.data ?? {}
    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId ? { ...m, reactions: data.reactions || {}, mine: data.mine || [] } : m,
      ),
    )
  }

  function openVoice({ screenshare = false }: LooseProps = {}) {
    setPreferScreenshare(screenshare)
    setVoiceOpen(true)
  }

  if (error) {
    return (
      <div className="od-chat-panel od-chat-panel--error">
        <PageStatus error={error} errorMessage="Unable to load chat." />
      </div>
    )
  }

  const active = channels.find((c) => c.id === activeId)
  const roomChannels = channels.filter((c) => c.kind !== 'dm' && c.type !== 'dm')
  const dmChannels = channels.filter((c) => c.kind === 'dm' || c.type === 'dm')
  const showArchive = canArchiveChannel(active, viewer)
  const showLeave = canLeaveChannel(active)
  const attachDisabled = !activeId || attachAvailable === false || attachBusy || viewerIsChild
  const canSend =
    Boolean(activeId) && (Boolean(body.trim()) || pendingAttachments.length > 0) && !attachBusy
  const attachHint = viewerIsChild
    ? ATTACH_HINT_CHILD
    : attachAvailable === false
      ? ATTACH_HINT_UNAVAILABLE
      : null

  return (
    <div
      className={`od-chat-panel${compact ? ' od-chat-panel--compact' : ''}${expanded ? ' od-chat-panel--expanded' : ''}`}
    >
      <div className="od-chat-layout">
        <ChatRoomsAside
          canCreateRooms={canCreateRooms}
          activeId={activeId}
          channels={channels}
          channelsLoading={channelsLoading}
          createRoom={createRoom}
          creatingRoom={creatingRoom}
          dmChannels={dmChannels}
          dmName={dmName}
          loadChannels={loadChannels}
          newRoomName={newRoomName}
          openDm={openDm}
          roomChannels={roomChannels}
          runSearch={runSearch}
          searchHits={searchHits}
          searchQ={searchQ}
          setActiveId={setActiveId}
          setDmName={setDmName}
          setNewRoomName={setNewRoomName}
          setPreferScreenshare={setPreferScreenshare}
          setSearchHits={setSearchHits}
          setSearchQ={setSearchQ}
          setShowTools={setShowTools}
          setVoiceChannel={setVoiceChannel}
          setVoiceOpen={setVoiceOpen}
          showTools={showTools}
        />

        <section className="od-chat-thread" aria-label="Messages">
          <ChatThreadHead
            expanded={expanded}
            onClose={onClose}
            onExpandToggle={onExpandToggle}
            active={active}
            archiveActiveRoom={archiveActiveRoom}
            leaveActiveRoom={leaveActiveRoom}
            openVoice={openVoice}
            preferScreenshare={preferScreenshare}
            roomActionBusy={roomActionBusy}
            showArchive={showArchive}
            showLeave={showLeave}
            toggleMute={toggleMute}
            voiceOpen={voiceOpen}
          />

          {voiceOpen ? (
            <div className="od-chat-voice od-chat-voice--header" aria-label="Voice and screenshare">
              <div className="od-chat-voice__bar">
                <span className="od-chat-voice__label">
                  {preferScreenshare ? 'Screenshare entry' : 'Voice entry'}
                </span>
                <button
                  type="button"
                  className="od-chat-icon-btn"
                  onClick={() => setVoiceOpen(false)}
                  aria-label="Hide voice panel"
                >
                  Hide
                </button>
              </div>
              <VoiceLobby
                compact
                room={voiceChannel?.room || ''}
                defaultScreenshare={preferScreenshare}
                roomLabel={
                  voiceChannel
                    ? `${voiceChannel.name}${preferScreenshare ? ' · Screenshare' : ''}`
                    : preferScreenshare
                      ? 'Household lobby · Screenshare'
                      : 'Household lobby'
                }
              />
              {!voiceChannel ? (
                <p className="od-chat-voice__hint">
                  This is the shared household lobby, not this conversation. Pick a voice channel in
                  a space to talk there instead.
                </p>
              ) : null}
            </div>
          ) : null}

          {msg ? (
            <p
              className={`od-chat-status${msgIsError ? ' is-error' : ''}`}
              role={msgIsError ? 'alert' : 'status'}
            >
              {msg}
            </p>
          ) : null}

          <ChatMessageList
            activeId={activeId}
            listEndRef={listEndRef}
            messages={messages}
            reactionItems={reactionItems}
            setReplyTo={setReplyTo}
            toggleReaction={toggleReaction}
          />

          <ChatComposer
            active={active}
            activeId={activeId}
            attachAvailable={attachAvailable}
            attachDisabled={attachDisabled}
            attachHint={attachHint}
            body={body}
            canSend={canSend}
            composerRef={composerRef}
            emojiPickerId={emojiPickerId}
            fileInputRef={fileInputRef}
            handleAttachFiles={handleAttachFiles}
            insertEmoji={insertEmoji}
            pendingAttachments={pendingAttachments}
            reactionItems={reactionItems}
            replyTo={replyTo}
            sendMessage={sendMessage}
            setBody={setBody}
            setPendingAttachments={setPendingAttachments}
            setReplyTo={setReplyTo}
            setShowEmojiPicker={setShowEmojiPicker}
            showEmojiPicker={showEmojiPicker}
            viewerIsChild={viewerIsChild}
          />
        </section>
      </div>
    </div>
  )
}
