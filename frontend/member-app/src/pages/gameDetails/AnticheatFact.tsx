import type { AnticheatReport } from './detailsTypes'
import { safeHttpUrl } from '../../utils/safeUrl'

/** Plain words for the community vocabulary. Reports, never a guarantee. */
export const ANTICHEAT_LABEL: Record<string, string> = {
  supported: 'Supported',
  running: 'Running',
  planned: 'Planned',
  broken: 'Broken',
  denied: 'Denied',
  unknown: 'Unknown',
}

/** The Details "Anti-cheat" fact (INSP-35): status chip, the anti-cheat names, and the source. */
export function AnticheatFact({ report }: { report: AnticheatReport }) {
  const status = String(report.status || 'unknown').toLowerCase()
  const label = ANTICHEAT_LABEL[status] || ANTICHEAT_LABEL.unknown
  const names = (report.anticheats || []).filter(Boolean)
  const reports = Number(report.reports || 0)
  const note =
    reports > 0
      ? `community reports, ${reports} update${reports === 1 ? '' : 's'}`
      : 'community reports'
  return (
    <>
      <span className="od-details-page__anticheat" data-status={status}>
        {label}
      </span>
      {names.length ? <span>{names.join(', ')}</span> : null}
      <span className="od-details-page__anticheat-note">
        {safeHttpUrl(report.source_url) ? (
          <a
            href={safeHttpUrl(report.source_url) || undefined}
            target="_blank"
            rel="noreferrer noopener"
          >
            {note}
          </a>
        ) : (
          note
        )}
      </span>
    </>
  )
}
