import { useEffect, useRef, useState } from 'react'
import type { OpsIssues } from '../api/summary'

const labels: Record<string, string> = {
  good: 'All systems healthy',
  warn: 'Attention needed',
  bad: 'Action required',
}

export interface StatusBannerProps {
  issues?: OpsIssues | null
  asOf?: string | null
}

export function StatusBanner({ issues, asOf }: StatusBannerProps) {
  const requestedSeverity = issues?.overall ?? 'good'
  const severity: keyof typeof labels =
    requestedSeverity === 'good' || requestedSeverity === 'warn' || requestedSeverity === 'bad'
      ? requestedSeverity
      : 'good'
  const [announcement, setAnnouncement] = useState(labels[severity])
  const previousSeverity = useRef(severity)

  useEffect(() => {
    if (previousSeverity.current === severity) return

    previousSeverity.current = severity
    setAnnouncement(labels[severity])
  }, [severity])

  return (
    <section className={`ops-status ops-status--${severity}`} aria-label="System status">
      <strong>{labels[severity]}</strong>
      {asOf && <span>Updated {new Date(asOf).toLocaleString()}</span>}
      <span className="ops-glance__sr-only" role="status" aria-live="polite" aria-atomic="true">
        {announcement}
      </span>
    </section>
  )
}
