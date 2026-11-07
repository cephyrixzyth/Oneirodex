import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { fetchMemberProfile } from '../api/social'
import { PageStatus } from '../components/PageStatus'

function formatDuration(totalSeconds: any) {
  const seconds = Math.max(0, Math.floor(Number(totalSeconds) || 0))
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`
  if (m > 0) return `${m}m`
  return `${seconds}s`
}

export function MemberProfilePage() {
  const { userId } = useParams()
  const [reload, setReload] = useState(0)
  const [profile, setProfile] = useState<any>({ userId: null, data: null, error: null })

  useEffect(() => {
    const controller = new AbortController()
    let current = true
    setProfile({ userId, data: null, error: null })
    fetchMemberProfile(userId, { signal: controller.signal })
      .then((data) => {
        if (current) setProfile({ userId, data, error: null })
      })
      .catch((err: any) => {
        if (current && err.name !== 'AbortError') setProfile({ userId, data: null, error: err })
      })
    return () => {
      current = false
      controller.abort()
    }
  }, [userId, reload])

  const currentProfile = profile.userId === userId
    ? profile
    : { userId, data: null, error: null }
  const { data, error } = currentProfile

  if (error || !data) {
    return (
      <div className="od-more-page">
        <PageStatus
          loading={!error}
          error={error}
          onRetry={error ? () => setReload((value) => value + 1) : null}
          errorMessage="Unable to load profile."
          loadingMessage="Loading profile…"
        />
      </div>
    )
  }

  const user = data.user || {}
  const presence = data.presence || {}

  return (
    <div className="od-more-page">
      <div className="od-page-header">
        <h1>{user.name}</h1>
      </div>
      <p className="od-more-page__lede">
        {presence.status === 'in-game' && presence.game_name
          ? `Playing ${presence.game_name}`
          : presence.status || 'offline'}
        {' · '}
        {formatDuration(data.total_seconds)} total
        {data.is_friend ? ' · Friend' : ''}
        {data.is_self ? ' · You' : ''}
      </p>
      {user.about ? <p>{user.about}</p> : null}
      <section>
        <h2>Recent games</h2>
        {(data.recent_games || []).length === 0 ? (
          <p className="od-more-page__lede">No recent games visible to you.</p>
        ) : (
          <ul>
            {data.recent_games.map((row: any) => (
              <li key={row.game_uuid}>
                <Link to={`/game_details/${row.game_uuid}`}>{row.game_name}</Link>
                {' — '}
                {formatDuration(row.total_seconds)}
              </li>
            ))}
          </ul>
        )}
      </section>
      <p>
        <Link to="/activity">Back to Activity</Link>
      </p>
    </div>
  )
}
