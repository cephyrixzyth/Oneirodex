import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, useShellConfig } from '@oneirodex/ui'
import {
  acceptFriend as apiAcceptFriend,
  fetchActivity,
  fetchFriends,
  fetchSocialStatus as fetchSocial,
  rejectFriend as apiRejectFriend,
  removeFriend as apiRemoveFriend,
  requestFriend as apiRequestFriend,
} from '../api/social'
import { ContextBar } from '../chrome/ContextBar'
import { PageStatus } from '../components/PageStatus'
import { VoiceLobby } from '../components/VoiceLobby'
import '../styles/panelGrid.css'

function presenceLabel(status: any) {
  if (status === 'in-game') return 'In game'
  if (status === 'online') return 'Online'
  if (status === 'away') return 'Away'
  return 'Offline'
}

const ACTIVITY_VIEWS = [
  { id: 'all', label: 'Everyone' },
  { id: 'friends', label: 'Friends only' },
]

export function ActivityPage() {
  const shellConfig = useShellConfig()
  const useNewChrome = Boolean(shellConfig.enableNewChrome)
  const [data, setData] = useState<any>(null)
  const [social, setSocial] = useState<any>(null)
  const [friends, setFriends] = useState<any[]>([])
  const [friendName, setFriendName] = useState('')
  const [error, setError] = useState<any>(null)
  const [friendMsg, setFriendMsg] = useState<any>(null)
  const [friendsOnly, setFriendsOnly] = useState(false)

  const reload = useCallback(() => {
    const controller = new AbortController()
    Promise.all([
      fetchActivity({ signal: controller.signal, friendsOnly }),
      fetchSocial({ signal: controller.signal }),
      fetchFriends({ signal: controller.signal }),
    ])
      .then(([activity, socialStatus, friendData]) => {
        setData(activity)
        setSocial(socialStatus)
        setFriends(Array.isArray(friendData?.friends) ? friendData.friends : [])
      })
      .catch((err: any) => {
        if (err.name !== 'AbortError') setError(err)
      })
    return () => controller.abort()
  }, [friendsOnly])

  useEffect(() => {
    const cleanup = reload()
    let source: EventSource | null | undefined
    let sseLive = false
    let timer = 0

    function pollFallback() {
      fetchActivity({ friendsOnly })
        .then(setData)
        .catch(() => {})
      fetchSocial()
        .then(setSocial)
        .catch(() => {})
    }

    function startSlowPoll() {
      window.clearInterval(timer)
      // SSE healthy: rare safety poll. SSE dead: 30s fallback.
      const ms = sseLive ? 120000 : 30000
      timer = window.setInterval(pollFallback, ms)
    }

    let sseTimer = 0

    function connectSse() {
      try {
        source = new EventSource('/api/activity/stream')
        source.addEventListener('hello', () => {
          sseLive = true
          startSlowPoll()
        })
        source.addEventListener('activity', () => {
          sseLive = true
          fetchActivity({ friendsOnly })
            .then(setData)
            .catch(() => {})
          fetchSocial()
            .then(setSocial)
            .catch(() => {})
        })
        source.addEventListener('presence', () => {
          sseLive = true
          fetchSocial()
            .then(setSocial)
            .catch(() => {})
          fetchFriends()
            .then((friendData) => {
              setFriends(Array.isArray(friendData?.friends) ? friendData.friends : [])
            })
            .catch(() => {})
        })
        source.onerror = () => {
          sseLive = false
          startSlowPoll()
        }
      } catch {
        source = null
        sseLive = false
      }
    }

    // Poll first; defer SSE so initial Activity fetches aren't racing the stream.
    startSlowPoll()
    sseTimer = window.setTimeout(connectSse, 500)
    return () => {
      cleanup?.()
      window.clearInterval(timer)
      window.clearTimeout(sseTimer)
      source?.close()
    }
  }, [friendsOnly, reload])

  async function requestFriend(event: any) {
    event.preventDefault()
    const username = friendName.trim()
    if (!username) return
    setFriendMsg(null)
    try {
      const body = await apiRequestFriend(username)
      setFriendName('')
      if (body.existing) {
        setFriendMsg('Already connected or pending')
      } else if (body.sent) {
        setFriendMsg('Friend request sent')
      } else {
        setFriendMsg(body.message || 'If that username exists, a friend request was sent.')
      }
      const friendData = await fetchFriends()
      setFriends(Array.isArray(friendData?.friends) ? friendData.friends : [])
    } catch (err: any) {
      setFriendMsg(err.message || 'Friend request failed')
    }
  }

  async function acceptFriend(id: any) {
    await apiAcceptFriend(id)
    const friendData = await fetchFriends()
    setFriends(Array.isArray(friendData?.friends) ? friendData.friends : [])
  }

  async function rejectFriend(id: any) {
    await apiRejectFriend(id)
    const friendData = await fetchFriends()
    setFriends(Array.isArray(friendData?.friends) ? friendData.friends : [])
  }

  async function removeFriend(id: any) {
    await apiRemoveFriend(id)
    const friendData = await fetchFriends()
    setFriends(Array.isArray(friendData?.friends) ? friendData.friends : [])
  }

  return (
    <>
      {useNewChrome ? (
        <ContextBar
          views={ACTIVITY_VIEWS}
          activeView={friendsOnly ? 'friends' : 'all'}
          onSelectView={(id: any) => setFriendsOnly(id === 'friends')}
        />
      ) : null}
      <div className="od-more-page od-panels">
        {useNewChrome ? null : (
          <>
            <div className="od-page-header od-panels__full">
              <h1>Activity</h1>
            </div>
            <p className="od-more-page__lede">
              Friends, presence, and who’s playing — social hangout is on by default for the
              household.
            </p>
            <label className="od-more-page__lede">
              <input
                type="checkbox"
                checked={friendsOnly}
                onChange={(event) => setFriendsOnly(event.target.checked)}
              />{' '}
              Friends only feed
            </label>
          </>
        )}

        {social?.community_chat_url ? (
          <p>
            <a
              className="od-btn"
              href={social.community_chat_url}
              target="_blank"
              rel="noopener noreferrer"
              title={social.community_chat_url}
            >
              {social.community_chat_label || 'Open community'}
            </a>
          </p>
        ) : null}

        <section>
          <h2>Friends</h2>
          <form className="od-updates__search-form" onSubmit={requestFriend}>
            <label>
              Add by username
              <input
                value={friendName}
                onChange={(e) => setFriendName(e.target.value)}
                placeholder="household username"
                autoComplete="off"
              />
            </label>
            <Button type="submit">Request</Button>
          </form>
          {friendMsg ? <p role="status">{friendMsg}</p> : null}
          {friends.length === 0 ? (
            <PageStatus emptyMessage="No friends yet — add someone by username." />
          ) : (
            <ul>
              {friends.map((row) => (
                <li key={row.id}>
                  <Link to={`/members/${row.user?.id}`}>
                    <strong>{row.user?.name}</strong>
                  </Link>{' '}
                  — {row.status}
                  {row.user?.presence?.status
                    ? ` · ${presenceLabel(row.user.presence.status)}`
                    : ''}
                  {row.direction === 'incoming' && row.status === 'pending' ? (
                    <>
                      {' '}
                      <Button type="button" onClick={() => void acceptFriend(row.id)}>
                        Accept
                      </Button>{' '}
                      <Button type="button" onClick={() => void rejectFriend(row.id)}>
                        Decline
                      </Button>
                    </>
                  ) : null}
                  {row.status === 'accepted' ? (
                    <>
                      {' '}
                      <Button type="button" onClick={() => void removeFriend(row.id)}>
                        Unfriend
                      </Button>
                    </>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </section>

        <VoiceLobby />
        {error ? (
          <PageStatus
            error={error}
            errorMessage="Unable to load activity."
            onRetry={reload}
            retryLabel="Retry"
          />
        ) : !data ? (
          <PageStatus loading loadingMessage="Loading activity…" />
        ) : data.restricted ? (
          <p>Activity feed is limited for this account.</p>
        ) : (
          <>
            <section>
              <h2>Now playing</h2>
              {(data.now_playing || []).length === 0 ? (
                <PageStatus emptyMessage="Nobody is playing right now." />
              ) : (
                <ul>
                  {data.now_playing.map((row: any) => (
                    <li key={`np-${row.session_id}`}>
                      {row.user_id ? (
                        <Link to={`/members/${row.user_id}`}>
                          <strong>{row.user}</strong>
                        </Link>
                      ) : (
                        <strong>{row.user}</strong>
                      )}{' '}
                      — <Link to={`/game_details/${row.game_uuid}`}>{row.game_name}</Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section>
              <h2>Recent</h2>
              <ul>
                {(data.activity || []).map((row: any) => (
                  <li key={row.session_id}>
                    {row.user_id ? (
                      <Link to={`/members/${row.user_id}`}>
                        <strong>{row.user}</strong>
                      </Link>
                    ) : (
                      <strong>{row.user}</strong>
                    )}{' '}
                    played <Link to={`/game_details/${row.game_uuid}`}>{row.game_name}</Link>
                    {row.is_playing ? ' (live)' : ''}
                  </li>
                ))}
              </ul>
            </section>
          </>
        )}
      </div>
    </>
  )
}
