/**
 * Shared Ops / Dashboard widgets for the observability console.
 * Keep presentation here; pages own fetch / poll cadence.
 */
import type { Key, ReactNode, SVGProps } from 'react'

import {
  libraryHealthFactorsGradeClass,
  normalizeLibraryHealth,
  partitionIssues,
  resolveBannerSeverity,
  severityLabel,
  topLibraryHealthFactors,
} from './opsFormat'
export * from './opsFormat'

/** Loose Backend-shaped rows (ops summary / issues / health) — narrow at use. */
export type OpsRow = Record<string, unknown>

/**
 * Reusable metric strip (GT-C2 / UID-014).
 *
 * Dashboard and Ops were the only two pages with colour-reactive metric
 * chrome, because the strip markup lived inline in those two files. Every other
 * admin page — Users, Support, Invites, Storage, Extensions — had no summary
 * row at all, which is what "admin metrics not color-reactive like dashboard"
 * was describing.
 *
 * Pass `items` as `{ id, label, value, hint, tone }`. Entries are skipped when
 * `value` is undefined so a page can declare optional metrics without branching.
 */
export interface MetricStripItem {
  id?: string
  label?: ReactNode
  value?: ReactNode
  hint?: ReactNode
  tone?: string
}

function OpsIssueRows({
  items,
  toneFallback = 'warn',
}: {
  items: OpsRow[]
  toneFallback?: string
}) {
  return items.map((item) => {
    const tone =
      item.severity === 'bad' || item.severity === 'warn' || item.severity === 'info'
        ? item.severity === 'info'
          ? 'warn'
          : item.severity
        : toneFallback
    return (
      <li
        key={(item.id ?? item.message) as string}
        className={`od-ops-issues__item od-ops-issues__item--${tone}`}
      >
        {item.href ? (
          <a href={item.href as string}>{item.message as ReactNode}</a>
        ) : (
          <span>{item.message as ReactNode}</span>
        )}
      </li>
    )
  })
}

export function OpsIssuesList({ items }: { items?: unknown }) {
  const { action, soft } = partitionIssues(items)
  if (!action.length && !soft.length) return null
  return (
    <div className="od-ops-issues-folds">
      {action.length ? (
        <section
          className="od-ops-issues-fold od-ops-issues-fold--action"
          aria-label="Action required"
        >
          <h2 className="od-ops-issues-fold__title">Action required</h2>
          <ul className="od-ops-issues">
            <OpsIssueRows items={action} toneFallback="bad" />
          </ul>
        </section>
      ) : null}
      {soft.length ? (
        <section
          className="od-ops-issues-fold od-ops-issues-fold--soft"
          aria-label="Warning / Info"
        >
          <h2 className="od-ops-issues-fold__title">Warning / Info</h2>
          <ul className="od-ops-issues">
            <OpsIssueRows items={soft} toneFallback="warn" />
          </ul>
        </section>
      ) : null}
    </div>
  )
}

function IconReset(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" width="1.15em" height="1.15em" aria-hidden="true" {...props}>
      <path
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M3 12a9 9 0 1 0 3-6.7M3 4v5h5"
      />
    </svg>
  )
}

export function OpsStatusBanner({
  severity = 'good',
  loading = false,
  unavailable = false,
  asOf,
  items,
  ariaLabel = 'System status',
  onRefresh = null,
  refreshing = false,
  refreshDisabled = false,
}: {
  severity?: string
  loading?: boolean
  unavailable?: boolean
  asOf?: string
  items?: any
  ariaLabel?: string
  onRefresh?: (() => void) | null
  refreshing?: boolean
  refreshDisabled?: boolean
}) {
  const tone = loading ? 'loading' : unavailable ? 'na' : resolveBannerSeverity(items, severity)
  const label = loading
    ? 'Checking health…'
    : unavailable
      ? 'Health status unavailable'
      : severityLabel(tone)
  return (
    <section
      className={`od-ops-status od-ops-status--${tone}`}
      aria-label={ariaLabel}
      aria-busy={loading ? 'true' : undefined}
    >
      <div className="od-ops-status__head">
        <strong>{label}</strong>
        {/* Trail chrome only when this banner owns Updated/refresh. Dashboard
            and Ops put those in the top bar, so leave the slot empty. */}
        {asOf || onRefresh ? (
          <div className="od-ops-status__trail">
            {asOf ? (
              <span className="od-ops-status__asof">Updated {new Date(asOf).toLocaleString()}</span>
            ) : null}
            {onRefresh ? (
              <button
                type="button"
                className="od-cbtn od-ops-status__refresh"
                aria-label={refreshing ? 'Refreshing' : 'Refresh dashboard'}
                title="Refresh"
                onClick={onRefresh}
                disabled={refreshDisabled || refreshing}
              >
                <IconReset />
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
      <OpsIssuesList items={items} />
    </section>
  )
}

export function MeterBar({
  label,
  percent,
  detail,
}: {
  label?: any
  percent?: unknown
  detail?: any
}) {
  const pct =
    percent == null || !Number.isFinite(Number(percent))
      ? null
      : Math.max(0, Math.min(100, Number(percent)))
  const tone = pct == null ? 'na' : pct >= 95 ? 'bad' : pct >= 85 ? 'warn' : 'good'
  return (
    <div className={`od-ops-meter od-ops-meter--${tone}`}>
      <div className="od-ops-meter__label">
        <span>{label}</span>
        <span>{pct == null ? 'n/a' : `${pct}%`}</span>
      </div>
      <div className="od-ops-meter__track" aria-hidden="true">
        <div className="od-ops-meter__fill" style={{ width: pct == null ? '0%' : `${pct}%` }} />
      </div>
      {detail ? <div className="od-ops-meter__detail">{detail}</div> : null}
    </div>
  )
}

const METRIC_TONES = new Set(['good', 'fair', 'poor', 'na', 'action', 'warning', 'info'])

export function MetricTile({
  label,
  value,
  hint,
  tone,
}: {
  label?: any
  value?: any
  hint?: any
  tone?: string
}) {
  const toneClass = tone && METRIC_TONES.has(tone) ? ` od-ops-metric--${tone}` : ''
  return (
    <div className={`od-ops-metric${toneClass}`}>
      <div className="od-ops-metric__label">{label}</div>
      <div className="od-ops-metric__value">{value}</div>
      {hint ? <div className="od-ops-metric__hint">{hint}</div> : null}
    </div>
  )
}

export interface OpsBuild {
  version?: string | null
  commit?: string | null
  built_at?: string | null
  schema_revision?: string | null
  schema_head?: string | null
  /** `null` = could not tell, which is not the same as "nothing pending". */
  migration_pending?: boolean | null
  generator_version?: number | null
}

/** Short, local, and dropped entirely when the stamp is absent. */
function builtAtLabel(value?: string | null): string {
  if (!value) return ''
  const when = new Date(value)
  if (Number.isNaN(when.getTime())) return ''
  return when.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

/**
 * What is running, and is it what shipped?
 *
 * One component for both boards — the Dashboard and Ops keep independent
 * widget maps over one payload, and two hand-rolled copies of this would be
 * two places to disagree about the thing whose entire job is to be
 * authoritative.
 *
 * `migration_pending` is the loud line. The schema revision on its own is a
 * hex string nobody can check by eye; the comparison against the revision this
 * code expects is what turns it into an answer.
 */
export function BuildTile({ build }: { build?: OpsBuild | null }) {
  if (!build) {
    return <MetricTile label="Build" value="n/a" hint="build data unavailable" tone="na" />
  }

  const pending = build.migration_pending
  const tone = pending === true ? 'action' : pending === false ? 'good' : 'na'
  const stamp = [build.commit, builtAtLabel(build.built_at)].filter(Boolean).join(' · ')

  return (
    <div className={`od-ops-metric od-ops-metric--${tone}`}>
      <div className="od-ops-metric__label">Build</div>
      <div className="od-ops-metric__value">{build.version || 'n/a'}</div>
      {/* Absent rather than invented: a hand-built image has no commit and
          says so, the way the GPU tile reads n/a with no reader. */}
      <div className="od-ops-metric__hint">{stamp || 'no build stamp'}</div>
      <div className="od-ops-metric__hint">
        {pending === true
          ? `migration pending — schema ${build.schema_revision || '?'} , code wants ${build.schema_head || '?'}`
          : pending === false
            ? `schema ${build.schema_revision} · up to date`
            : 'schema unknown'}
      </div>
      <div className="od-ops-metric__hint">themes generator {build.generator_version ?? 'n/a'}</div>
    </div>
  )
}

export function MetricStrip({
  items = [],
  label = 'Key metrics',
}: {
  items?: MetricStripItem[]
  label?: string
}) {
  const rows = (Array.isArray(items) ? items : []).filter(
    (item) => item && item.value !== undefined,
  )
  if (!rows.length) return null
  return (
    <div className="od-ops-strip" aria-label={label}>
      {rows.map((item) => (
        <MetricTile
          key={item.id || String(item.label)}
          label={item.label}
          value={item.value}
          hint={item.hint}
          tone={item.tone}
        />
      ))}
    </div>
  )
}

/**
 * Top health factors list for Library pulse / Services-adjacent.
 * Honest empty when health absent or factors empty.
 * Grade cues: poor → danger left edge; fair → warn-gold (good/na unchanged).
 */
export function LibraryHealthFactors({ health, limit = 3 }: { health?: unknown; limit?: number }) {
  const n = normalizeLibraryHealth(health)
  if (!n) {
    return (
      <p className="od-admin-lede od-ops-health-factors od-ops-health-factors--empty">
        Library health not scored yet.
      </p>
    )
  }
  const gradeClass = libraryHealthFactorsGradeClass(n.grade)
  const factors = topLibraryHealthFactors(health, limit)
  if (!factors.length) {
    return (
      <p
        className={`od-admin-lede od-ops-health-factors od-ops-health-factors--empty${gradeClass}`}
      >
        {n.thin
          ? n.note || 'Library health sample thin — no factor breakdown yet.'
          : n.grade
            ? `Grade ${n.grade} · no top factors.`
            : 'No top health factors.'}
      </p>
    )
  }
  return (
    <ul className={`od-ops-health-factors${gradeClass}`} aria-label="Top health factors">
      {factors.map((f) => {
        const key = (f.id || f.label) as Key
        const label = (f.label || f.id || 'factor') as ReactNode
        return (
          <li key={key} className="od-ops-health-factors__item">
            <span className="od-ops-health-factors__label">{label}</span>
            {f.count != null && Number.isFinite(Number(f.count)) ? (
              <span className="od-ops-health-factors__count">{f.count as ReactNode}</span>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}
