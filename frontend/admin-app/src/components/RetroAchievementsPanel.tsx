import { useCallback, useEffect, useState } from 'react'
import { getJson, postJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { PageStatus, Button } from '@oneirodex/ui'
import { showToast } from '../utils/toast'

const STATUS_ENDPOINT = '/api/retroachievements/status'
const MATCH_ENDPOINT = '/api/retroachievements/match'

interface ConsoleRow {
  platform: string
  console_id: number
  indexed_hashes: number
  index_fetched_at: string | null
  matched_games: number
}

interface RaStatus {
  configured: boolean
  username: string | null
  has_key: boolean
  supported_platforms: string[]
  consoles: ConsoleRow[]
}

interface MatchSummary {
  platform: string
  indexed_hashes: number
  considered: number
  hashed: number
  matched: number
}

/**
 * RetroAchievements (R1/R2) on the Emulators page: is it configured, which
 * systems can be hashed here, and a Match button per system. Matching is
 * read-only against the provider and only ever *shows* a set — nothing
 * played in the browser unlocks anything, and the copy says so.
 */
export function RetroAchievementsPanel() {
  const [status, setStatus] = useState<RaStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [lastRun, setLastRun] = useState<MatchSummary | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    return getJson(STATUS_ENDPOINT)
      .then((data) => setStatus(data as RaStatus))
      .catch((err) => setError(err))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const match = useCallback(
    async (platform: string, rehash = false) => {
      setBusy(platform)
      try {
        const summary = (await postJson(MATCH_ENDPOINT, { platform, rehash })) as MatchSummary
        setLastRun(summary)
        showToast(
          `${summary.platform}: ${summary.matched} of ${summary.considered} matched a set (${summary.indexed_hashes} hashes indexed).`,
          'success',
        )
        await load()
      } catch (err) {
        showToast(errorText(err) || 'RetroAchievements match failed.', 'error')
      } finally {
        setBusy(null)
      }
    },
    [load],
  )

  return (
    <section
      className="od-admin-panel"
      id="retroachievements"
      aria-labelledby="od-retroachievements-heading"
    >
      <h2 id="od-retroachievements-heading" className="od-section-head__title">
        RetroAchievements
      </h2>
      <p className="od-admin-lede">
        Matches cartridge ROMs to community achievement sets by the hash RetroAchievements uses, so
        a title can say it has a set and a member can see their own progress. Read-only: nothing
        played in the browser unlocks anything, hardcore or softcore.
      </p>
      <PageStatus
        loading={loading}
        loadingMessage="Reading RetroAchievements status…"
        error={error}
        onRetry={load}
        errorMessage="Could not read RetroAchievements status."
        inline
      />
      {loading || error || !status ? null : !status.configured ? (
        <p className="od-muted" data-testid="ra-unconfigured">
          Not configured. Save the household username and web API key under Admin → Integrations →
          RetroAchievements (get the web API key from retroachievements.org → Settings → Keys), then
          match a system here.
          {status.has_key && !status.username
            ? ' The key is present; the username is missing.'
            : ''}
          {!status.has_key && status.username
            ? ' The username is present; the key is missing.'
            : ''}
        </p>
      ) : (
        <>
          <p className="od-muted">
            Signed in as <strong>{status.username}</strong>. Systems this build can hash:{' '}
            {status.supported_platforms.length}. Disc systems are left unmatched rather than matched
            wrongly.
          </p>
          <table className="od-table od-table--compact" aria-label="RetroAchievements by system">
            <thead>
              <tr>
                <th scope="col">System</th>
                <th scope="col">Hashes indexed</th>
                <th scope="col">Index fetched</th>
                <th scope="col">Games with a set</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {status.consoles.map((row) => (
                <tr key={row.platform} data-platform={row.platform}>
                  <td>{row.platform}</td>
                  <td>{row.indexed_hashes}</td>
                  <td>
                    {row.index_fetched_at ? new Date(row.index_fetched_at).toLocaleString() : '—'}
                  </td>
                  <td>{row.matched_games}</td>
                  <td>
                    <Button
                      type="button"
                      size="sm"
                      disabled={busy !== null}
                      onClick={() => match(row.platform)}
                      aria-label={`Match ${row.platform}`}
                    >
                      {busy === row.platform ? 'Matching…' : 'Match'}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {lastRun ? (
            // Recap only — the toast already announced the result, and a second
            // live region would double-speak it (and trips the status-language
            // ratchet, which wants PageStatus for anything that announces).
            <p className="od-muted" data-testid="ra-last-run">
              Last run — {lastRun.platform}: {lastRun.considered} considered, {lastRun.hashed} newly
              hashed, {lastRun.matched} matched.
            </p>
          ) : null}
        </>
      )}
    </section>
  )
}
