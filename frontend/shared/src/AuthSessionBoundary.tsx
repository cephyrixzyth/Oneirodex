import { useEffect, useRef, useState, type ReactNode } from 'react'
import { readAuthBoundaryEpoch, subscribeAuthBoundary } from './authBoundary.js'
import './AuthSessionBoundary.css'

/** Retire the old private tree; a new identity requires fresh server bootstrap. */
export function AuthSessionBoundary({ children }: { children?: ReactNode }) {
  const [initialEpoch] = useState(readAuthBoundaryEpoch)
  const [ended, setEnded] = useState(false)
  const notice = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (ended) return
    return subscribeAuthBoundary(() => setEnded(true), initialEpoch)
  }, [ended, initialEpoch])
  useEffect(() => {
    if (ended) notice.current?.focus()
  }, [ended])
  if (!ended) return children
  return (
    <div ref={notice} className="od-session-ended" role="alert" tabIndex={-1}>
      <h1>Sign in to continue</h1>
      <p>This page needs a fresh sign-in check.</p>
      <a className="od-session-ended__link" href="/login">
        Sign in
      </a>
    </div>
  )
}
