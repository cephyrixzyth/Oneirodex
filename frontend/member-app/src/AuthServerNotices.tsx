import { useState } from 'react'

interface ServerNotice {
  role: 'alert' | 'status'
  message: string
}

function readServerNotices(): ServerNotice[] {
  const raw = document.getElementById('member-auth-root')?.getAttribute('data-auth-notices')
  if (!raw) return []
  try {
    const payload: unknown = JSON.parse(raw)
    if (!Array.isArray(payload)) return []
    return payload.flatMap((item): ServerNotice[] => {
      if (!item || typeof item !== 'object') return []
      const notice = item as Record<string, unknown>
      if (
        (notice.role !== 'alert' && notice.role !== 'status') ||
        typeof notice.message !== 'string'
      ) return []
      return [{ role: notice.role, message: notice.message }]
    })
  } catch {
    return []
  }
}

export function AuthServerNotices() {
  const [notices, setNotices] = useState<ServerNotice[]>(readServerNotices)

  return notices.map((item, index) => (
    <div className="auth-pilot__server-notice" role={item.role} key={`${index}-${item.message}`}>
      <span>{item.message}</span>
      <button
        type="button"
        className="auth-pilot__server-notice-dismiss"
        aria-label="Close"
        onClick={() => setNotices((current) => current.filter((_, itemIndex) => itemIndex !== index))}
      >
        ×
      </button>
    </div>
  ))
}
