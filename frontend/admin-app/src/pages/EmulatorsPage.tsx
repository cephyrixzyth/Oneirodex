import { useEffect, useState } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import { getJson, putJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { BrowserPlayerPilot } from '../components/BrowserPlayerPilot'
import { RetroAchievementsPanel } from '../components/RetroAchievementsPanel'
import { EmulatorFirmwarePanel } from '../components/EmulatorFirmwarePanel'
import { Page } from '../components/Page'

/**
 * Admin › Emulators. Second H-D.5 port.
 *
 * The preferred-core form was `templates/admin/emulator_profiles.html` +
 * `static/js/od_admin_emulator_profiles.js`; the browser-player pilot,
 * RetroAchievements and firmware panels were already React, mounted as an
 * island under the Jinja form. Now one page owns all four.
 *
 * `/api/emulator-profiles` GET returns `{ catalog: { PLATFORM: [core…] },
 * profiles: { PLATFORM: core | null } }`; PUT `{ profiles }` answers the same
 * shape. An empty selection means "default (first core)", sent as `null`.
 */

export interface EmulatorProfilesData {
  catalog: Record<string, string[]>
  profiles: Record<string, string | null>
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
}

function normalize(data: unknown): EmulatorProfilesData {
  const root = asRecord(data)
  const catalog: Record<string, string[]> = {}
  for (const [platform, cores] of Object.entries(asRecord(root.catalog))) {
    catalog[platform] = Array.isArray(cores) ? cores.map(String) : []
  }
  const profiles: Record<string, string | null> = {}
  for (const [platform, core] of Object.entries(asRecord(root.profiles))) {
    profiles[platform] = core ? String(core) : null
  }
  return { catalog, profiles }
}

export function EmulatorProfilesForm() {
  const [catalog, setCatalog] = useState<Record<string, string[]>>({})
  const [profiles, setProfiles] = useState<Record<string, string | null>>({})
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setLoadError(null)
    getJson('/api/emulator-profiles')
      .then((data) => {
        if (cancelled) return
        const next = normalize(data)
        setCatalog(next.catalog)
        setProfiles(next.profiles)
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [reloadKey])

  async function save() {
    if (busy) return
    setBusy(true)
    setStatus('Saving…')
    try {
      const body: Record<string, string | null> = {}
      for (const platform of Object.keys(catalog)) body[platform] = profiles[platform] || null
      const saved = normalize(await putJson('/api/emulator-profiles', { profiles: body }))
      if (Object.keys(saved.catalog).length) setCatalog(saved.catalog)
      setProfiles(saved.profiles)
      setStatus('Saved.')
    } catch (err) {
      setStatus(errorText(err) || 'Save failed')
    } finally {
      setBusy(false)
    }
  }

  const platforms = Object.keys(catalog).sort()

  return (
    <section className="od-admin-panel" aria-labelledby="emu-profiles-heading">
      <h2 id="emu-profiles-heading" className="h5">
        Preferred cores
      </h2>
      <p className="text-muted">
        Prefer a WebRetro libretro core per console platform. Play Now on game details uses the
        preferred core when set.
      </p>
      <PageStatus loading={loading} error={loadError} onRetry={() => setReloadKey((k) => k + 1)}>
        <p className="od-admin-lede od-admin-lede--flush" aria-live="polite">
          {status}
        </p>
        {platforms.length === 0 ? (
          <p className="text-muted">No emulator platforms available.</p>
        ) : (
          <div className="od-emu-list">
            {platforms.map((platform) => (
              <div
                key={platform}
                className="od-emu-row mb-2 d-flex gap-2 align-items-center flex-wrap"
              >
                <label style={{ minWidth: 140 }} htmlFor={`emu-${platform}`}>
                  <strong>{platform}</strong>
                </label>
                <select
                  id={`emu-${platform}`}
                  className="form-select"
                  style={{ maxWidth: 280 }}
                  value={profiles[platform] || ''}
                  onChange={(e) =>
                    setProfiles((prev) => ({ ...prev, [platform]: e.target.value || null }))
                  }
                >
                  <option value="">Default (first core)</option>
                  {(catalog[platform] || []).map((core) => (
                    <option key={core} value={core}>
                      {core}
                    </option>
                  ))}
                </select>
              </div>
            ))}
            <Button variant="primary" className="mt-2" disabled={busy} onClick={save}>
              Save profiles
            </Button>
          </div>
        )}
      </PageStatus>
    </section>
  )
}

export function EmulatorsPage() {
  return (
    <Page
      title="Emulators"
      lede={
        <>
          Which core plays each console in the browser, the browser-player pilot, RetroAchievements,
          and the firmware each core needs.
        </>
      }
    >
      <EmulatorProfilesForm />
      <BrowserPlayerPilot />
      <RetroAchievementsPanel />
      <EmulatorFirmwarePanel />
    </Page>
  )
}
