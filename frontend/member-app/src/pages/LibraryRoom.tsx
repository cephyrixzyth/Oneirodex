import { useCallback, useEffect, useRef, useState } from 'react'
import type { createRoom, RoomGame, RoomView, Station } from './roomScene'
import { createMoonfallSession } from './pinball/session'
import type { MoonfallSession } from './pinball/session'
import { MoonfallPanel, moonfallMenu } from './pinball/MoonfallPanel'
import { MoonfallNavigationGuard } from './pinball/MoonfallNavigationGuard'

const stations: { id: Station; name: string }[] = [
  { id: 'library', name: 'Library wall' },
  { id: 'reading', name: 'Reading desk' },
  { id: 'lounge', name: 'Lounge' },
  { id: 'overview', name: 'Room overview' },
]
const shelfSize = 4
const comfortModes = ['Standard', 'Seated', 'Close reach'] as const
type ComfortMode = (typeof comfortModes)[number]
interface Props {
  memberId?: string
  initiallyOpen?: boolean
  favoriteMessage: string
  onFavorite: () => void
  scope: string
  onFavorites: () => void
  onScope: () => void
  games: RoomGame[]
  page: number
  pages: number
  pageSize: number
  total: number
  ready: boolean
  error: boolean
  selected: RoomGame | null
  detailMessage: string
  onSelect: (id: string) => void
  onPage: (page: number) => void
}
export function LibraryRoom({
  initiallyOpen = false,
  memberId = '',
  favoriteMessage,
  onFavorite,
  scope,
  onScope,
  onFavorites,
  games,
  page,
  pages,
  pageSize,
  total,
  ready,
  error,
  selected,
  detailMessage,
  onSelect,
  onPage,
}: Props) {
  const storageKey = memberId ? 'od.room.comfort.v1.' + memberId : ''
  const [comfort, setComfort] = useState<ComfortMode>(() => {
    try {
      const value = storageKey && localStorage.getItem(storageKey)
      return comfortModes.find((mode) => mode === value) || 'Standard'
    } catch {
      return 'Standard'
    }
  })
  function chooseComfort(mode: ComfortMode) {
    setComfort(mode)
    try {
      if (storageKey) localStorage.setItem(storageKey, mode)
    } catch {
      /* session only */
    }
  }
  const [largeText, setLargeText] = useState(() => {
    try {
      return Boolean(storageKey && localStorage.getItem(storageKey + '.largeText') === 'true')
    } catch {
      return false
    }
  })
  function chooseText(value: boolean) {
    setLargeText(value)
    try {
      if (storageKey) localStorage.setItem(storageKey + '.largeText', String(value))
    } catch {
      /* session only */
    }
  }
  const lastScope = useRef(scope)
  const [open, setOpen] = useState(initiallyOpen)
  const [started, setStarted] = useState(false)
  const [capable, setCapable] = useState(false)
  const [immersive, setImmersive] = useState(false)
  const [requesting, setRequesting] = useState(false)
  const [problem, setProblem] = useState('')
  const [visitedRoom, setVisitedRoom] = useState('')
  const [requestedRoom, setRequestedRoom] = useState('')
  const [accountTheme, setAccountTheme] = useState(
    () => document.documentElement.dataset.theme || 'default',
  )
  const effectiveTheme = visitedRoom || accountTheme
  const [gameView, setGameView] = useState<ReturnType<MoonfallSession['view']> | null>(null)
  const session = useRef<MoonfallSession | null>(null)
  const changingRoom = useRef(false)
  const pendingChange = useRef<{ change: () => void; kind: 'user' | 'theme' } | null>(null)
  const leave = useCallback(
    async (change: () => void, kind: 'user' | 'theme' = 'user') => {
      // Keep the latest explicit choice while a save finishes. Background theme
      // synchronization must not replace a pending user action.
      if (!pendingChange.current || kind === 'user' || pendingChange.current.kind === 'theme')
        pendingChange.current = { change, kind }
      if (changingRoom.current) return
      changingRoom.current = true
      try {
        const safe = (await session.current?.beforeLeave()) ?? true
        if (!pendingChange.current) return
        if (
          !safe &&
          !window.confirm(
            'Your Moonfall progress could not be saved. Leave and lose unsaved changes?',
          )
        ) {
          if (pendingChange.current.kind === 'user') setRequestedRoom(visitedRoom)
          return
        }
        const request = pendingChange.current
        pendingChange.current = null
        request.change()
      } finally {
        pendingChange.current = null
        changingRoom.current = false
      }
    },
    [visitedRoom],
  )
  useEffect(() => {
    if (!open) return
    const sync = () => {
      const theme = document.documentElement.dataset.theme || 'default'
      if (theme === accountTheme) return
      if (visitedRoom) setAccountTheme(theme)
      else void leave(() => setAccountTheme(theme), 'theme')
    }
    sync()
    const observer = new MutationObserver(sync)
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme'],
    })
    return () => observer.disconnect()
  }, [open, visitedRoom, accountTheme, leave])
  const [shelf, setShelf] = useState(0)
  const canvas = useRef<HTMLCanvasElement>(null)
  const engine = useRef<ReturnType<typeof createRoom> | null>(null)
  const opener = useRef<HTMLButtonElement>(null)
  const shelfCount = Math.max(1, Math.ceil(games.length / shelfSize))
  const index = scope === lastScope.current ? Math.min(shelf, shelfCount - 1) : 0
  useEffect(() => {
    lastScope.current = scope
    setShelf(0)
  }, [scope])
  const entries = games.slice(index * shelfSize, (index + 1) * shelfSize)
  const shelfLabel = error
    ? 'Catalog unavailable'
    : !ready
      ? 'Loading catalog…'
      : total
        ? `Titles ${(page - 1) * pageSize + index * shelfSize + 1}–${(page - 1) * pageSize + index * shelfSize + entries.length} of ${total}`
        : scope === 'favorites'
          ? 'Favorite a title at the reading desk'
          : 'No titles on this wall'
  const view: RoomView = {
    comfort,
    largeText,
    collection: scope === 'collection',
    favoriteMessage,
    games: entries,
    selected,
    detailMessage,
    shelf: shelfLabel,
    previous: ready && (index > 0 || page > 1),
    next: ready && (index + 1 < shelfCount || page < pages),
  }
  function activate(id: string) {
    if (id.startsWith('@moonfall-')) {
      if (id === '@moonfall-open') engine.current?.move('pinball')
      else void session.current?.command(id.slice('@moonfall-'.length))
      return
    }
    if (id === '@text') {
      chooseText(!largeText)
      return
    }
    if (id === '@comfort') {
      chooseComfort(comfortModes[(comfortModes.indexOf(comfort) + 1) % comfortModes.length])
      return
    }
    if (id === '@favorite') {
      onFavorite()
      return
    }
    if (id === '@favorites') {
      onFavorites()
      engine.current?.move('library')
      return
    }
    if (id === '@scope') {
      onScope()
      return
    }
    if (id === '@previous') {
      if (!view.previous) return
      if (index > 0) setShelf(index - 1)
      else {
        setShelf(Math.ceil(pageSize / shelfSize) - 1)
        onPage(page - 1)
      }
    } else if (id === '@next') {
      if (!view.next) return
      if (index + 1 < shelfCount) setShelf(index + 1)
      else {
        setShelf(0)
        onPage(page + 1)
      }
    } else {
      onSelect(id)
    }
  }
  const latest = useRef({ view, activate })
  useEffect(() => {
    latest.current = { view, activate }
  })
  useEffect(() => {
    if (!open || !canvas.current) return
    let cancelled = false
    setProblem('')
    setStarted(false)
    setImmersive(false)
    setCapable(false)
    setRequesting(false)
    const target = canvas.current
    import('./roomScene')
      .then(({ createRoom }) => {
        if (cancelled) return
        let owned: ReturnType<typeof createRoom> | null = null
        const scene = createRoom(
          target,
          (id) => latest.current.activate(id),
          setImmersive,
          setProblem,
          {
            theme: effectiveTheme,
            onGameCommand: (action) => {
              if (!cancelled && owned && engine.current === owned)
                void session.current?.command(action)
            },
            onGameSnapshot: (event) => {
              if (!cancelled && owned && engine.current === owned) session.current?.observe(event)
            },
          },
        )
        owned = scene
        engine.current = scene
        if (scene.game) {
          const ownedSession = createMoonfallSession(scene.game, memberId, () => {
            if (cancelled || session.current !== ownedSession) return
            const value = ownedSession.view()
            setGameView(value)
            scene.setGameMenu(moonfallMenu(value))
          })
          session.current = ownedSession
          setGameView(ownedSession.view())
          void ownedSession.initialize()
        }
        scene.update(latest.current.view)
        setStarted(true)
        navigator.xr
          ?.isSessionSupported('immersive-vr')
          .then((ok) => {
            if (!cancelled) setCapable(ok)
          })
          .catch(() => {})
      })
      .catch(() => {
        if (!cancelled)
          setProblem('This browser could not open the 3D room. The catalog is available below.')
      })
    return () => {
      cancelled = true
      pendingChange.current = null
      session.current?.dispose()
      session.current = null
      setGameView(null)
      engine.current?.dispose()
      engine.current = null
    }
  }, [open, effectiveTheme, memberId])
  useEffect(() => {
    engine.current?.update(latest.current.view)
  }, [
    games,
    selected,
    detailMessage,
    page,
    shelf,
    ready,
    error,
    total,
    pages,
    scope,
    favoriteMessage,
    comfort,
    largeText,
  ])
  async function enter() {
    setRequesting(true)
    setProblem('')
    try {
      await engine.current?.enter()
    } catch {
      setProblem(
        'The headset session could not start. Check the headset connection and browser permission, then try again.',
      )
    } finally {
      setRequesting(false)
    }
  }
  function close() {
    void leave(() => {
      setOpen(false)
      setVisitedRoom('')
      setRequestedRoom('')
      opener.current?.focus()
    })
  }
  return (
    <section className="od-library-room" aria-labelledby="od-room-title">
      <div className="od-library-room__header">
        <div>
          <h2 id="od-room-title">Library room</h2>
          <p>Browse the wall, take a title to the reading desk, or settle into the lounge.</p>
        </div>
        <button
          type="button"
          ref={opener}
          className="od-cbtn"
          aria-expanded={open}
          onClick={() => (open ? close() : setOpen(true))}
        >
          {open ? 'Close room' : 'Open room'}
        </button>
      </div>
      {open && (
        <>
          <canvas
            key={effectiveTheme + ':' + memberId}
            ref={canvas}
            className="od-library-room__canvas"
            tabIndex={0}
            aria-label="Interactive library room. Drag to look, or use the station buttons below."
          />
          {problem && <p role="alert">{problem}</p>}
          {!started && !problem && <p role="status">Preparing the room…</p>}
          {started && (
            <>
              <div className="od-library-room__controls" role="group" aria-label="Room stations">
                <label>
                  Visit room{' '}
                  <select
                    aria-label="Visit room"
                    value={requestedRoom}
                    aria-busy={requestedRoom !== visitedRoom}
                    onChange={(event) => {
                      const value = event.target.value
                      // Controlled inputs need their displayed value updated in
                      // this event; activating the scene still waits for saving.
                      setRequestedRoom(value)
                      void leave(() => setVisitedRoom(value))
                    }}
                  >
                    <option value="">Follow my theme</option>
                    <option value="oneirodex">Aurora Observatory</option>
                    <option value="greenhouse">Mosslight</option>
                    <option value="afterglow">Afterglow Arcade</option>
                    <option value="monochrome">Graphite Studio</option>
                    <option value="signal">Signal Room</option>
                    <option value="tape-deck">Tape Deck</option>
                    <option value="deep-space">Deep Space</option>
                    <option value="tideglass">Tideglass</option>
                  </select>
                </label>
                <label>
                  Room comfort{' '}
                  <select
                    value={comfort}
                    onChange={(e) => chooseComfort(e.target.value as ComfortMode)}
                  >
                    {comfortModes.map((mode) => (
                      <option key={mode}>{mode}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={largeText}
                    onChange={(event) => chooseText(event.target.checked)}
                  />
                  Large reading text
                </label>
                <button
                  type="button"
                  className="od-cbtn"
                  onClick={() => engine.current?.recenter()}
                >
                  Recenter view
                </button>
                {stations.map((s) => (
                  <button
                    type="button"
                    key={s.id}
                    className="od-cbtn"
                    onClick={() => engine.current?.move(s.id)}
                  >
                    {s.name}
                  </button>
                ))}
                {gameView && (
                  <button
                    type="button"
                    className="od-cbtn"
                    onClick={() => engine.current?.move('pinball')}
                  >
                    Moonfall Pinball
                  </button>
                )}
                {gameView && (
                  <>
                    <button
                      type="button"
                      className="od-cbtn"
                      onClick={() => engine.current?.instrument('telescope')}
                    >
                      Adjust telescope
                    </button>
                    <button
                      type="button"
                      className="od-cbtn"
                      onClick={() => engine.current?.instrument('orrery')}
                    >
                      Turn orrery
                    </button>
                  </>
                )}
                {immersive ? (
                  <button
                    type="button"
                    className="od-cbtn"
                    onClick={() => void engine.current?.exit()}
                  >
                    Leave headset
                  </button>
                ) : capable ? (
                  <button
                    type="button"
                    className="od-cbtn"
                    disabled={requesting}
                    onClick={() => void enter()}
                  >
                    Enter headset
                  </button>
                ) : null}
              </div>
              {requestedRoom !== visitedRoom && <p role="status">Changing rooms…</p>}
              {gameView && (
                <MoonfallPanel
                  view={gameView}
                  command={(action) => void session.current?.command(action)}
                  input={(action, pressed, source) =>
                    engine.current?.game?.input(action, pressed, source)
                  }
                  settings={(value) => engine.current?.game?.setSettings(value)}
                />
              )}
              {gameView && session.current && <MoonfallNavigationGuard session={session.current} />}
              <p className="od-library-room__help">
                {capable
                  ? 'Point and select in your headset.'
                  : 'Desktop preview. A connected WebXR headset on HTTPS or localhost enables immersive mode.'}{' '}
                Drag or use the arrow keys to look. WASD moves. Home returns to the station.
              </p>
              <div className="od-library-room__controls" role="group" aria-label="Room shelf">
                <button
                  type="button"
                  className="od-cbtn"
                  disabled={!view.previous}
                  onClick={() => activate('@previous')}
                >
                  Previous shelf
                </button>
                <span aria-live="polite">{shelfLabel}</span>
                <button
                  type="button"
                  className="od-cbtn"
                  disabled={!view.next}
                  onClick={() => activate('@next')}
                >
                  Next shelf
                </button>
                <button
                  type="button"
                  className="od-cbtn"
                  aria-pressed={scope === 'favorites'}
                  onClick={() => activate('@favorites')}
                >
                  Favorite shelf
                </button>
              </div>
            </>
          )}
        </>
      )}
    </section>
  )
}
