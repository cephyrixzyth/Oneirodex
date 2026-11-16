import type { ReactNode } from 'react'
import { safeExternalUrl } from '@oneirodex/ui'
import {
  buildDupeCompare,
  formatByteSize,
  formatDiskDate,
  type CompareSideData,
} from '../unmatchedDupe'
import {
  hasStageEHints,
  normalizeStageECandidates,
  normalizeStageEMeta,
  stageEChipSources,
  stageEMatchModeLabel,
  stageESourceLabel,
} from '../stageECandidates'
import type { UnmatchedFolderRow } from './dupeGlanceTypes'

/* Helpers and the compare sub-components moved out of DupeGlance (v11 cycle, H-D.2), unchanged. */

export const STATUS_FALLBACK: Record<string, string> = {
  Duplicate:
    'Another library game already uses this IGDB match and the folder title looks like the same game.',
  Unmatched: 'Could not auto-match to IGDB (or IGDB already used by a different-titled folder).',
  Ignore: 'Folder is ignored and will not be scanned.',
  Pending: 'Awaiting classification.',
}

/** Machine codes from duplicate_check / scan → one-line librarian copy. */
export const MATCH_REASON_LABELS: Record<string, string> = {
  same_path: 'Same on-disk path as an existing library game.',
  title_vs_folder: 'Folder title closely matches an existing library game folder.',
  title_vs_library_name: 'Folder title closely matches an existing library game name.',
  title_below_threshold:
    'IGDB hit exists, but the folder title differs too much to auto-mark as duplicate.',
}

export const MARK_KINDS = [
  { kind: 'experience', label: 'Mark as Soft title' },
  { kind: 'emulator', label: 'Mark as Emulator' },
  { kind: 'tool', label: 'Mark as Utility' },
]

export const SUGGESTED_KIND_LABELS: Record<string, string> = {
  experience: 'Soft title',
  emulator: 'Emulator',
  tool: 'Utility',
  game: 'Game',
}

/** Normalize API `suggested_kind` (null-safe). Backend may omit until list enrichment lands. */
export function normalizeSuggestedKind(value: unknown): string | null {
  if (value == null || value === '') return null
  const kind = String(value).trim().toLowerCase()
  return SUGGESTED_KIND_LABELS[kind] ? kind : null
}

/**
 * One-line “why unmatched?” explainer. Prefers Backend `why_unmatched` /
 * `unmatched_reason` when present; otherwise match_reason (+ suggested_kind).
 * Null-safe — returns null when nothing useful.
 */
export function formatWhyUnmatched(row: UnmatchedFolderRow | null | undefined): string | null {
  if (!row || typeof row !== 'object') return null

  const summary =
    (row.why_unmatched != null && String(row.why_unmatched).trim()) ||
    (row.unmatched_reason != null && String(row.unmatched_reason).trim()) ||
    ''
  if (summary) return summary

  const rawReason = row.match_reason == null ? '' : String(row.match_reason).trim()
  let reason = ''
  if (rawReason) {
    const code = rawReason.toLowerCase()
    reason = MATCH_REASON_LABELS[code] || rawReason
  }

  const suggestedKind = normalizeSuggestedKind(row.suggested_kind)
  const suggestedLabel =
    (row.suggested_kind_label != null && String(row.suggested_kind_label).trim()) ||
    (suggestedKind ? SUGGESTED_KIND_LABELS[suggestedKind] : '')
  const candidate =
    row.suggested_candidate_name == null ? '' : String(row.suggested_candidate_name).trim()

  if (suggestedLabel) {
    const hint = candidate
      ? `Scan suggests cataloging as ${suggestedLabel} (e.g. ${candidate}).`
      : `Scan suggests cataloging as ${suggestedLabel}.`
    if (reason) return `${reason} ${hint}`
    if (row.status === 'Unmatched' || row.status === 'Pending') {
      return `No IGDB game match. ${hint}`
    }
    return hint
  }

  if (reason) return reason
  const status = row.status as string | undefined
  if (status && STATUS_FALLBACK[status]) return STATUS_FALLBACK[status]
  return null
}

/**
 * Format Backend `match_score` for display beside Why unmatched?
 * Null-safe — returns null when missing / non-numeric.
 * Values ≤1 shown to 2 decimals; 0–100 integers shown as whole numbers.
 */
export function formatMatchScore(score: unknown): string | null {
  if (score == null || score === '') return null
  const n = Number(score)
  if (!Number.isFinite(n)) return null
  if (n > 1 && n <= 100) {
    return Number.isInteger(n) ? String(n) : String(Math.round(n * 10) / 10)
  }
  return (Math.round(n * 100) / 100).toFixed(2)
}

/**
 * Ordered Stage A peel trail from Backend `transforms[]`.
 * Soft-degrades when missing / mid-rollout — returns [].
 * @returns {{ stage: string, before: string, after: string, reason: string }[]}
 */
export interface TransformStep {
  stage: string
  before: string
  after: string
  reason: string
}

export function normalizeTransforms(row: UnmatchedFolderRow | null | undefined): TransformStep[] {
  if (!row || typeof row !== 'object') return []
  const raw = row.transforms
  if (!Array.isArray(raw) || raw.length === 0) return []
  return raw
    .filter((step): step is Record<string, unknown> => step && typeof step === 'object')
    .map((step) => ({
      stage: step.stage == null ? '' : String(step.stage).trim(),
      before: step.before == null ? '' : String(step.before),
      after: step.after == null ? '' : String(step.after),
      reason: step.reason == null ? '' : String(step.reason).trim(),
    }))
    .filter((step) => step.stage || step.before || step.after)
}

/** Compact expander: stage · before → after · reason (reason optional). */
export function TransformTrail({ transforms }: { transforms?: TransformStep[] }) {
  const steps = Array.isArray(transforms) ? transforms : []
  if (!steps.length) return null
  return (
    <details className="od-dupe-glance__transforms">
      <summary className="od-dupe-glance__transforms-summary">
        Name transform trail ({steps.length})
      </summary>
      <ol className="od-dupe-glance__transform-list">
        {steps.map((step, index) => (
          <li key={`${step.stage}-${index}`} className="od-dupe-glance__transform-step">
            <span className="od-dupe-glance__transform-stage">{step.stage || '—'}</span>
            <span className="od-dupe-glance__transform-pair">
              <code>{step.before}</code>
              <span aria-hidden="true"> → </span>
              <code>{step.after}</code>
            </span>
            {step.reason ? (
              <span className="od-dupe-glance__transform-reason">{step.reason}</span>
            ) : null}
          </li>
        ))}
      </ol>
    </details>
  )
}

/**
 * Quiet Stage E propose-only candidates (Moby / TheGamesDB).
 * Soft-degrades when list API has not flattened proposal fields yet.
 */
export function StageECandidates({ row }: { row: UnmatchedFolderRow | null | undefined }) {
  if (!hasStageEHints(row)) return null
  const candidates = normalizeStageECandidates(row)
  const meta = normalizeStageEMeta(row)
  const sources = stageEChipSources(candidates)
  const chipDetail = sources.length ? sources.join(' · ') : 'catalog'
  const title =
    'Propose-only catalog hints after Stage D miss — not auto-matched. Use Fix search / Identify to apply.'
  return (
    <div className="od-dupe-glance__stage-e">
      <span className="od-dupe-glance__stage-e-chip" title={title}>
        Stage E · propose only · {chipDetail}
      </span>
      {candidates.length > 0 ? (
        <details className="od-dupe-glance__stage-e-details">
          <summary className="od-dupe-glance__stage-e-summary">
            Stage E candidates ({candidates.length})
          </summary>
          <p className="od-dupe-glance__stage-e-note">
            Catalog hints only — Identify to apply. Not auto-matched.
          </p>
          <ul className="od-dupe-glance__stage-e-list">
            {candidates.map((hit, index) => {
              const source = stageESourceLabel(hit.source)
              const mode = stageEMatchModeLabel(hit.match_mode)
              const label = hit.name || hit.id || 'Candidate'
              const hitUrl = safeExternalUrl(hit.url)
              return (
                <li
                  key={`${hit.source}-${hit.id || hit.name}-${index}`}
                  className="od-dupe-glance__stage-e-hit"
                >
                  <span className="od-dupe-glance__stage-e-source">{source}</span>
                  {hitUrl ? (
                    <a
                      className="od-dupe-glance__stage-e-name"
                      href={hitUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {label}
                    </a>
                  ) : (
                    <span className="od-dupe-glance__stage-e-name">{label}</span>
                  )}
                  {mode ? <span className="od-dupe-glance__stage-e-mode">{mode}</span> : null}
                </li>
              )
            })}
          </ul>
        </details>
      ) : meta ? (
        <p className="od-dupe-glance__stage-e-meta" title={title}>
          {meta.match_reason || 'Stage E propose-only'} — Identify to apply.
        </p>
      ) : null}
    </div>
  )
}

export function markKindsOrdered(suggestedKind: string | null) {
  if (!suggestedKind) return MARK_KINDS
  const preferred = MARK_KINDS.find((row) => row.kind === suggestedKind)
  if (!preferred) return MARK_KINDS
  return [preferred, ...MARK_KINDS.filter((row) => row.kind !== suggestedKind)]
}

export const EMPTY_FIELD = '—'
export const EMPTY_FIELD_TITLE = 'Not provided by API yet'

export function CompareField({
  label,
  value,
  emptyTitle = EMPTY_FIELD_TITLE,
  children,
}: {
  label?: ReactNode
  value?: unknown
  emptyTitle?: string
  children?: ReactNode
}) {
  const hasValue = value != null && String(value).trim() !== ''
  return (
    <div className="od-dupe-glance__compare-field">
      <dt>{label}</dt>
      <dd>
        {children != null ? (
          children
        ) : hasValue ? (
          <span>{String(value)}</span>
        ) : (
          <span className="od-dupe-glance__compare-empty" title={emptyTitle}>
            {EMPTY_FIELD}
          </span>
        )}
      </dd>
    </div>
  )
}

export function CompareSide({
  side,
  why,
  onOpenPath,
  pathLabel,
}: {
  side: CompareSideData | null
  why?: string | null
  onOpenPath?: (v: { path: unknown; label: string; matchReason?: string }) => void
  pathLabel: string
}) {
  if (!side) {
    return (
      <div className="od-dupe-glance__compare-side od-dupe-glance__compare-side--empty">
        <p className="od-dupe-glance__compare-missing">No library hit yet</p>
      </div>
    )
  }
  const sizeLabel = formatByteSize(side.size_bytes)
  const dateLabel = formatDiskDate(side.mtime)
  const score = formatMatchScore(side.match_score)
  const path = side.path as string | undefined
  const uuid = side.uuid as string | undefined
  const coverUrl = side.cover_url as string | undefined
  return (
    <div className={`od-dupe-glance__compare-side od-dupe-glance__compare-side--${side.role}`}>
      <div className="od-dupe-glance__compare-head">
        {coverUrl ? (
          <img
            className="od-dupe-glance__dupe-thumb"
            src={coverUrl}
            alt=""
            width={28}
            height={36}
          />
        ) : side.role === 'library' ? (
          <span
            className="od-dupe-glance__dupe-thumb od-dupe-glance__dupe-thumb--empty"
            aria-hidden="true"
          />
        ) : null}
        <div className="od-dupe-glance__compare-head-text">
          <span className="od-dupe-glance__compare-role">{side.label}</span>
          {uuid ? (
            <a
              className="od-dupe-glance__dupe-title"
              href={`/game_details/${encodeURIComponent(uuid)}`}
            >
              {side.name as ReactNode}
            </a>
          ) : (
            <span className="od-dupe-glance__dupe-title">{side.name as ReactNode}</span>
          )}
          {score ? (
            <span className="od-dupe-glance__match-score" title="Match confidence score">
              {score}
            </span>
          ) : null}
        </div>
      </div>
      <dl className="od-dupe-glance__compare-fields">
        <CompareField label="Path">
          {path ? (
            <button
              type="button"
              className="od-dupe-glance__dupe-path"
              onClick={() =>
                onOpenPath?.({
                  path,
                  label: pathLabel,
                  matchReason: why || undefined,
                })
              }
            >
              {path}
            </button>
          ) : (
            <span className="od-dupe-glance__compare-empty" title={EMPTY_FIELD_TITLE}>
              {EMPTY_FIELD}
            </span>
          )}
        </CompareField>
        <CompareField label="Size" value={sizeLabel} />
        <CompareField label="Date" value={dateLabel} />
        {uuid ? (
          <CompareField label="UUID">
            <code className="od-dupe-glance__dupe-uuid">{uuid}</code>
          </CompareField>
        ) : null}
      </dl>
    </div>
  )
}

/**
 * Side-by-side Duplicate trail: this folder vs library hit (path · size · date).
 * Soft-degrades when size/date omitted by API.
 */
export function DupeCompare({
  row,
  onOpenPath,
}: {
  row: UnmatchedFolderRow
  onOpenPath?: (v: { path: unknown; label: string; matchReason?: string }) => void
}) {
  const compare = buildDupeCompare(row)
  if (!compare) return null
  const why = formatWhyUnmatched(row)
  return (
    <div
      className="od-dupe-glance__compare"
      role="group"
      aria-label="Duplicate side-by-side comparison"
    >
      <div className="od-dupe-glance__compare-banner">
        <span className="od-dupe-glance__dupe-label">Compare</span>
        <span className="od-dupe-glance__compare-banner-text">
          Folder vs library game — path, size, and date when the API provides them
        </span>
      </div>
      <div className="od-dupe-glance__compare-grid">
        <CompareSide
          side={compare.folder}
          why={why}
          onOpenPath={onOpenPath}
          pathLabel="Unmatched folder"
        />
        <CompareSide
          side={compare.library}
          why={why}
          onOpenPath={onOpenPath}
          pathLabel="Library game path"
        />
      </div>
    </div>
  )
}

/**
 * Compare unmatched / duplicate folders at a glance with fix actions.
 * Open path stays in a modal callback — never navigates to Auto Scan.
 */
// memo: DupeGlance does its own polling and its only prop is a stable setter, so
// it must not re-render every time its parent (ScansPage) re-renders on a 4s scan
// tick — that would re-lay-out its list and note <input> and make a password
// manager re-scan the subtree each tick.
export interface BadMatchReason {
  id: string
  label: string
}

export interface FixLog {
  ok: boolean
  message: string
  detail?: unknown
}
