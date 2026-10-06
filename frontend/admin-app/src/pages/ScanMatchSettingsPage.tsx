import { useEffect, useState, type FormEvent } from 'react'
import { Button, PageStatus } from '@oneirodex/ui'
import {
  PEEL_PROFILES,
  SAFE_VARIANT_KEYS,
  SAFE_VARIANT_LABELS,
  SCAN_MATCH_DEFAULTS,
  loadScanMatchConfig,
  saveScanMatchConfig,
} from '../api/scanMatchSettingsApi'
import { errorText } from '../utils/errorText'
import { Page } from '../components/Page'
import { AdminPageActions } from '../components/AdminPageActions'

function FieldNumber({
  id,
  label,
  hint,
  value,
  onChange,
  min = 0,
  max = 1,
  step = 0.01,
}: {
  id: string
  label: string
  hint?: string
  value: number | string
  onChange: (value: number | '') => void
  min?: number
  max?: number
  step?: number
}) {
  return (
    <label className="od-admin-field" htmlFor={id}>
      {label}
      <input
        id={id}
        type="number"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
      />
      {hint ? <span className="od-admin-hint">{hint}</span> : null}
    </label>
  )
}

export function ScanMatchSettingsPage() {
  const [form, setForm] = useState<Record<string, any>>({})
  const [exposed, setExposed] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [degradeReason, setDegradeReason] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    loadScanMatchConfig().then((result) => {
      if (cancelled) return
      setForm(result.form)
      setExposed(result.exposed)
      setDegradeReason(result.degradeReason)
      setLoading(false)
    })
    return () => {
      cancelled = true
    }
  }, [])

  function updateField(key: string, value: unknown) {
    setForm((prev) => ({ ...prev, [key]: value }))
    setMessage('')
    setError(null)
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !exposed.length) return
    setBusy(true)
    setMessage('')
    setError(null)
    try {
      const data = await saveScanMatchConfig(form, exposed)
      // Re-sync from response when Backend echoes keys (soft-degrade mid-save).
      if (
        data &&
        typeof data === 'object' &&
        (data.propose_only_scan !== undefined || data.peel_profile)
      ) {
        const next = { ...form }
        for (const key of exposed) {
          if (Object.prototype.hasOwnProperty.call(data, key)) {
            next[key] = data[key]
          }
        }
        setForm(next)
      }
      setMessage('Scan/match settings saved.')
    } catch (err) {
      setError(errorText(err) || 'Save failed.')
    } finally {
      setBusy(false)
    }
  }

  const canSave = exposed.length > 0 && !busy
  const showPropose = exposed.includes('propose_only_scan')
  const showDupe = exposed.includes('dupe_title_threshold')
  const showHigh = exposed.includes('match_high_threshold')
  const showGap = exposed.includes('match_ambiguous_gap')
  const showPeel = exposed.includes('peel_profile')
  const variantKeys = SAFE_VARIANT_KEYS.filter((key) => exposed.includes(key))

  return (
    <Page
      title="Scan / match policy"
      lede={
        <>
          Control how library scans propose vs auto-import matches. Many-leaf console libraries stay
          leaf-only — Oneirodex does not offer mega-library or depth-3 family walk options here. A
          high-confidence IGDB hit is still checked against Steam / GOG plus unique-exact MobyGames
          / TheGamesDB when those keys are set. A catalog disagreement (folder Doom / IGDB Doom 3)
          goes to Review as <code>catalog_disagreement</code> — it does not auto-import or peel the
          name down until it fits.
        </>
      }
    >
      <AdminPageActions label="Scan and matching actions">
        <a className="od-cbtn" href="/admin/libraries">
          Libraries
        </a>
        <a className="od-cbtn" href="/scan_management">
          Scan management
        </a>
      </AdminPageActions>
      {/* The two `od-admin-banner` blocks below stay as banners: they disclose
          rollout state (which policy fields Backend exposes), which is page
          content rather than a transient loading/error state. */}
      <PageStatus loading={loading} loadingMessage="Loading scan/match settings…" />

      {!loading && degradeReason ? (
        <div className="od-admin-banner od-admin-banner--warn" role="status">
          {degradeReason} <a href="/admin/new_server_settings">Open Server Settings</a> for
          propose-only until Backend exposes this API.
        </div>
      ) : null}

      {!loading && !degradeReason && exposed.length > 0 ? (
        <div className="od-admin-banner od-admin-banner--info" role="status">
          Editing {exposed.length} policy field{exposed.length === 1 ? '' : 's'} from Backend.
          Fields not yet rolled out stay hidden.
        </div>
      ) : null}

      {!loading && exposed.length > 0 ? (
        <form className="od-admin-panel od-scan-match" onSubmit={save}>
          {showPropose ? (
            <fieldset className="od-admin-fieldset">
              <legend>Propose-only (libraries)</legend>
              <label className="od-admin-field od-admin-field--check" htmlFor="propose_only_scan">
                <input
                  id="propose_only_scan"
                  type="checkbox"
                  checked={Boolean(form.propose_only_scan)}
                  onChange={(e) => updateField('propose_only_scan', e.target.checked)}
                />
                <span>
                  Propose-only scan mode
                  <span className="od-admin-hint">
                    When on, the scanner never auto-imports games — not even on a high-confidence
                    IGDB match. It writes proposal sidecars / unmatched rows for admin review.
                    Prefer this for a first pass on a large PC or many-leaf console tree.
                  </span>
                </span>
              </label>
            </fieldset>
          ) : null}

          {showDupe || showHigh || showGap ? (
            <fieldset className="od-admin-fieldset">
              <legend>Match confidence</legend>
              {showDupe ? (
                <FieldNumber
                  id="dupe_title_threshold"
                  label="Dupe title threshold"
                  hint={`Similarity (0–1) for duplicate-title detection. Default ${SCAN_MATCH_DEFAULTS.dupe_title_threshold}.`}
                  value={form.dupe_title_threshold ?? SCAN_MATCH_DEFAULTS.dupe_title_threshold}
                  onChange={(v) => updateField('dupe_title_threshold', v)}
                />
              ) : null}
              {showHigh ? (
                <FieldNumber
                  id="match_high_threshold"
                  label="High-confidence threshold"
                  hint={`Best candidate must score at least this (0–1) to auto-match. Default ${SCAN_MATCH_DEFAULTS.match_high_threshold}.`}
                  value={form.match_high_threshold ?? SCAN_MATCH_DEFAULTS.match_high_threshold}
                  onChange={(v) => updateField('match_high_threshold', v)}
                />
              ) : null}
              {showGap ? (
                <FieldNumber
                  id="match_ambiguous_gap"
                  label="Ambiguous gap"
                  hint={`Best-minus-second score gap required for high confidence. Default ${SCAN_MATCH_DEFAULTS.match_ambiguous_gap}.`}
                  value={form.match_ambiguous_gap ?? SCAN_MATCH_DEFAULTS.match_ambiguous_gap}
                  onChange={(v) => updateField('match_ambiguous_gap', v)}
                />
              ) : null}
            </fieldset>
          ) : null}

          {showPeel ? (
            <fieldset className="od-admin-fieldset">
              <legend>Peel profile</legend>
              <label className="od-admin-field" htmlFor="peel_profile">
                Name peel aggressiveness
                <select
                  id="peel_profile"
                  value={form.peel_profile || PEEL_PROFILES.CONSERVATIVE}
                  onChange={(e) => updateField('peel_profile', e.target.value)}
                >
                  <option value={PEEL_PROFILES.CONSERVATIVE}>
                    Conservative — safer peels; prefer human review on edge cases
                  </option>
                  <option value={PEEL_PROFILES.AGGRESSIVE}>
                    Aggressive — more Stage A/C peels and variants (still no mega-lib)
                  </option>
                </select>
                <span className="od-admin-hint">
                  Controls how eagerly folder names are cleaned and variant-expanded before IGDB
                  scoring. Does not change library depth or create mega-libraries.
                </span>
              </label>
            </fieldset>
          ) : null}

          {variantKeys.length > 0 ? (
            <fieldset className="od-admin-fieldset">
              <legend>Safe search variants</legend>
              <p className="od-admin-hint">
                Optional Backend toggles for Stage C variants. Hidden when not shipped.
              </p>
              {variantKeys.map((key) => {
                const meta = SAFE_VARIANT_LABELS[key as keyof typeof SAFE_VARIANT_LABELS] || {
                  label: key,
                  hint: '',
                }
                return (
                  <label key={key} className="od-admin-field od-admin-field--check" htmlFor={key}>
                    <input
                      id={key}
                      type="checkbox"
                      checked={Boolean(form[key])}
                      onChange={(e) => updateField(key, e.target.checked)}
                    />
                    <span>
                      {meta.label}
                      {meta.hint ? <span className="od-admin-hint">{meta.hint}</span> : null}
                    </span>
                  </label>
                )
              })}
            </fieldset>
          ) : null}

          <div className="od-admin-actions-row">
            <Button type="submit" disabled={!canSave}>
              {busy ? 'Saving…' : 'Save settings'}
            </Button>
            <a className="od-btn od-btn--ghost" href="/admin/settings">
              Settings hub
            </a>
            <a className="od-btn od-btn--ghost" href="/admin/new_server_settings">
              Server Settings
            </a>
          </div>
          {message ? (
            <p role="status" className="od-admin-lede od-admin-lede--ok">
              {message}
            </p>
          ) : null}
          <PageStatus error={error} />
        </form>
      ) : null}

      {!loading && !exposed.length ? (
        <div className="od-admin-panel">
          <p className="od-admin-lede">
            No scan/match policy fields are available from Backend yet. Defaults stay in code
            (`high_threshold` {SCAN_MATCH_DEFAULTS.match_high_threshold}, `ambiguous_gap`{' '}
            {SCAN_MATCH_DEFAULTS.match_ambiguous_gap}). Propose-only remains on{' '}
            <a href="/admin/new_server_settings">Server Settings</a>.
          </p>
          <div className="od-admin-actions-row">
            <a className="od-btn" href="/admin/new_server_settings">
              Open Server Settings
            </a>
            <a className="od-btn od-btn--ghost" href="/admin/settings">
              Settings hub
            </a>
          </div>
        </div>
      ) : null}
    </Page>
  )
}
