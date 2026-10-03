import { useEffect, useState, type FormEvent } from 'react'
import { Button, confirmAction } from '@oneirodex/ui'
import { PageStatus } from '@oneirodex/ui'
import { deleteJson, getJson, postJson, putJson } from '../api/adminApi'
import { errorText } from '../utils/errorText'
import { Page } from '../components/Page'

interface QualityProfile {
  id: string
  name?: string
  preferred_groups?: string[]
  preferred_patterns?: string[]
  blocked_groups?: string[]
  excluded_terms?: string[]
  min_size_mb?: number | null
  max_size_mb?: number | null
  prefer_repack?: boolean
}

interface QualityProfileForm {
  name: string
  preferred_groups: string
  preferred_patterns: string
  blocked_groups: string
  excluded_terms: string
  min_size_mb: number | string
  max_size_mb: number | string
  prefer_repack: boolean
}

interface ProbeResult {
  error?: string
  score?: number
  allowed?: boolean
  reasons?: string[]
}

const EMPTY_FORM: QualityProfileForm = {
  name: '',
  preferred_groups: '',
  preferred_patterns: '',
  blocked_groups: '',
  excluded_terms: '',
  min_size_mb: '',
  max_size_mb: '',
  prefer_repack: true,
}

function splitList(value: unknown): string[] {
  return String(value || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

function formFromProfile(profile: QualityProfile | null | undefined): QualityProfileForm {
  const p = profile || ({} as QualityProfile)
  return {
    name: p.name || '',
    preferred_groups: (p.preferred_groups || []).join(', '),
    preferred_patterns: (p.preferred_patterns || []).join(', '),
    blocked_groups: (p.blocked_groups || []).join(', '),
    excluded_terms: (p.excluded_terms || []).join(', '),
    min_size_mb: p.min_size_mb ?? '',
    max_size_mb: p.max_size_mb ?? '',
    prefer_repack: p.prefer_repack !== false,
  }
}

function bodyFromForm(form: QualityProfileForm) {
  return {
    name: String(form.name || '').trim() || 'Profile',
    preferred_groups: splitList(form.preferred_groups),
    preferred_patterns: splitList(form.preferred_patterns),
    blocked_groups: splitList(form.blocked_groups),
    excluded_terms: splitList(form.excluded_terms),
    min_size_mb: form.min_size_mb === '' || form.min_size_mb == null ? null : form.min_size_mb,
    max_size_mb: form.max_size_mb === '' || form.max_size_mb == null ? null : form.max_size_mb,
    prefer_repack: Boolean(form.prefer_repack),
  }
}

export function QualityProfilesPage() {
  const [profiles, setProfiles] = useState<QualityProfile[]>([])
  const [activeId, setActiveId] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [form, setForm] = useState<QualityProfileForm>(EMPTY_FORM)
  const [status, setStatus] = useState('Loading…')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [probeTitle, setProbeTitle] = useState('')
  const [probeResult, setProbeResult] = useState<ProbeResult | null>(null)

  function applyStore(data: any, preferId?: string) {
    const list: QualityProfile[] = Array.isArray(data?.profiles) ? data.profiles : []
    const nextActive = data?.active_id || ''
    setProfiles(list)
    setActiveId(nextActive)
    const nextSelected =
      (preferId && list.some((p) => p.id === preferId) && preferId) ||
      (selectedId && list.some((p) => p.id === selectedId) && selectedId) ||
      nextActive ||
      list[0]?.id ||
      ''
    setSelectedId(nextSelected)
    const selected = list.find((p) => p.id === nextSelected) || null
    setForm(formFromProfile(selected))
    const activeName = list.find((p) => p.id === nextActive)?.name || ''
    setStatus(
      activeName
        ? `Active: ${activeName} · editing ${selected?.name || '—'}`
        : list.length
          ? 'Loaded'
          : 'No profiles yet',
    )
  }

  async function reload(preferId?: string) {
    const data = await getJson('/api/quality-profiles')
    applyStore(data, preferId)
    return data
  }

  useEffect(() => {
    let cancelled = false
    reload().catch((err) => {
      if (!cancelled) {
        const text = errorText(err) || 'Failed to load'
        setError(text)
        setStatus(text)
      }
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only load
  }, [])

  function updateField<K extends keyof QualityProfileForm>(key: K, value: QualityProfileForm[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  function onSelectChange(id: string) {
    setSelectedId(id)
    const selected = profiles.find((p) => p.id === id) || null
    setForm(formFromProfile(selected))
    const activeName = profiles.find((p) => p.id === activeId)?.name || ''
    setStatus(`Editing ${selected?.name || '—'} · active ${activeName || '—'}`)
  }

  async function setActive() {
    if (!selectedId || busy) return
    setBusy(true)
    setError(null)
    try {
      const data = await putJson('/api/quality-profiles/active', { id: selectedId })
      applyStore(data, selectedId)
      setStatus('Active profile updated')
    } catch (err) {
      const text = errorText(err) || 'Activate failed'
      setError(text)
      setStatus(text)
    } finally {
      setBusy(false)
    }
  }

  async function createProfile() {
    if (busy) return
    const name = window.prompt('New profile name', 'Profile')
    if (name == null) return
    setBusy(true)
    setError(null)
    try {
      const created = await postJson('/api/quality-profiles', {
        name: String(name).trim() || 'Profile',
      })
      await reload(created.id || '')
      setStatus(`Created ${created.name || 'profile'}`)
    } catch (err) {
      const text = errorText(err) || 'Create failed'
      setError(text)
      setStatus(text)
    } finally {
      setBusy(false)
    }
  }

  async function deleteProfile() {
    if (!selectedId || profiles.length <= 1 || busy) return
    const selected = profiles.find((p) => p.id === selectedId)
    const ok = await confirmAction({
      title: `Delete profile “${selected?.name || selectedId}”?`,
      body: 'Downloads using it fall back to the default.',
      confirmLabel: 'Delete profile',
      cancelLabel: 'Keep it',
    })
    if (!ok) return
    setBusy(true)
    setError(null)
    try {
      const data = await deleteJson(`/api/quality-profiles/${encodeURIComponent(selectedId)}`)
      applyStore(data, '')
      setStatus('Profile deleted')
    } catch (err) {
      const text = errorText(err) || 'Delete failed'
      setError(text)
      setStatus(text)
    } finally {
      setBusy(false)
    }
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!selectedId || busy) return
    setBusy(true)
    setError(null)
    try {
      const saved = await putJson(
        `/api/quality-profiles/${encodeURIComponent(selectedId)}`,
        bodyFromForm(form),
      )
      await reload(saved.id || selectedId)
      setStatus('Saved')
    } catch (err) {
      const text = errorText(err) || 'Save failed'
      setError(text)
      setStatus(text)
    } finally {
      setBusy(false)
    }
  }

  async function runScoreProbe() {
    const title = probeTitle.trim()
    if (!title || busy) return
    setBusy(true)
    setProbeResult(null)
    try {
      const result = await postJson('/api/quality-profiles/score', {
        title,
        profile_id: selectedId || undefined,
      })
      setProbeResult(result)
    } catch (err) {
      setProbeResult({ error: errorText(err) || 'Score failed' })
    } finally {
      setBusy(false)
    }
  }

  if (error && profiles.length === 0) {
    return (
      <Page title="Quality Profiles">
        <PageStatus error={error} />
        <a className="od-btn" href="/admin/settings">
          Back to settings
        </a>
      </Page>
    )
  }

  return (
    <Page
      title="Quality Profiles"
      lede={
        <>
          Preferred / blocked release groups, naming patterns, excluded terms, and size bands. The
          active profile scores Arr search hits and extends scan name-clean filters.
        </>
      }
    >
      <div className="od-admin-panel od-admin-panel--stacked-below">
        <div className="od-admin-actions-row od-admin-actions-row--end od-admin-actions-row--flush">
          <label className="od-admin-field od-admin-field--grow od-admin-field--flush">
            Profiles
            <select
              className="od-admin-input"
              aria-label="Quality profiles"
              value={selectedId}
              onChange={(e) => onSelectChange(e.target.value)}
              disabled={!profiles.length}
            >
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name || 'Profile'}
                  {p.id === activeId ? ' (active)' : ''}
                </option>
              ))}
            </select>
          </label>
          <Button type="button" onClick={setActive} disabled={!selectedId || busy}>
            Set active
          </Button>
          <Button onClick={createProfile} disabled={busy}>
            New
          </Button>
          <Button
            type="button"
            onClick={deleteProfile}
            disabled={busy || profiles.length <= 1 || !selectedId}
          >
            Delete
          </Button>
        </div>
        <p className="od-admin-lede od-admin-lede--flush" aria-live="polite">
          {status}
        </p>
      </div>

      <form className="od-admin-panel" onSubmit={saveProfile}>
        <label className="od-admin-field">
          Profile name
          <input
            className="od-admin-input"
            value={form.name}
            onChange={(e) => updateField('name', e.target.value)}
            placeholder="Default"
          />
        </label>
        <label className="od-admin-field">
          Preferred groups (comma-separated)
          <input
            className="od-admin-input"
            value={form.preferred_groups}
            onChange={(e) => updateField('preferred_groups', e.target.value)}
            placeholder="GOG, Steam"
          />
        </label>
        <label className="od-admin-field">
          Preferred naming patterns (comma-separated)
          <input
            className="od-admin-input"
            value={form.preferred_patterns}
            onChange={(e) => updateField('preferred_patterns', e.target.value)}
            placeholder="repack, proper, -GOG"
          />
        </label>
        <label className="od-admin-field">
          Blocked groups (comma-separated)
          <input
            className="od-admin-input"
            value={form.blocked_groups}
            onChange={(e) => updateField('blocked_groups', e.target.value)}
            placeholder="scene-tag, unwanted-group"
          />
        </label>
        <label className="od-admin-field">
          Excluded terms (comma-separated)
          <input
            className="od-admin-input"
            value={form.excluded_terms}
            onChange={(e) => updateField('excluded_terms', e.target.value)}
            placeholder="CAM, TS, SAMPLE"
          />
        </label>
        <div className="od-admin-actions-row od-admin-actions-row--flush">
          <label className="od-admin-field od-admin-field--grow-sm">
            Min size (MB)
            <input
              className="od-admin-input"
              type="number"
              min="0"
              step="1"
              value={form.min_size_mb}
              onChange={(e) => updateField('min_size_mb', e.target.value)}
              placeholder="optional"
            />
          </label>
          <label className="od-admin-field od-admin-field--grow-sm">
            Max size (MB)
            <input
              className="od-admin-input"
              type="number"
              min="0"
              step="1"
              value={form.max_size_mb}
              onChange={(e) => updateField('max_size_mb', e.target.value)}
              placeholder="optional"
            />
          </label>
        </div>
        <label className="od-admin-field">
          <input
            type="checkbox"
            checked={form.prefer_repack}
            onChange={(e) => updateField('prefer_repack', e.target.checked)}
          />{' '}
          Prefer repack / proper in titles
        </label>
        <div className="od-admin-actions-row">
          <Button type="submit" disabled={!selectedId || busy}>
            Save profile
          </Button>
          <a className="od-btn" href="/admin/settings">
            Back to settings
          </a>
        </div>
      </form>

      <div className="od-admin-panel od-admin-panel--stacked">
        <h2 className="od-admin-panel-title">Test title score</h2>
        <p className="od-admin-lede">
          Probe <code>POST /api/quality-profiles/score</code> against the selected profile.
        </p>
        <div className="od-admin-actions-row od-admin-actions-row--end">
          <label className="od-admin-field od-admin-field--grow-lg od-admin-field--flush">
            Release title
            <input
              className="od-admin-input"
              value={probeTitle}
              onChange={(e) => setProbeTitle(e.target.value)}
              placeholder="Game.Title-GOG-repack"
              aria-label="Test release title"
            />
          </label>
          <Button type="button" onClick={runScoreProbe} disabled={!probeTitle.trim() || busy}>
            Score
          </Button>
        </div>
        {probeResult ? (
          <p className="od-admin-lede od-admin-lede--flush" aria-live="polite">
            {probeResult.error
              ? probeResult.error
              : `Score ${probeResult.score} · ${probeResult.allowed ? 'allowed' : 'blocked'}${
                  (probeResult.reasons || []).length
                    ? ` · ${(probeResult.reasons || []).join(', ')}`
                    : ''
                }`}
          </p>
        ) : null}
      </div>
    </Page>
  )
}
