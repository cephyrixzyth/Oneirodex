import { useContext, useEffect } from 'react'
import { UNSAFE_DataRouterContext, useBlocker } from 'react-router-dom'
import type { MoonfallSession } from './session'
type Session = Pick<MoonfallSession, 'hasUnsaved' | 'beforeLeave'>
function RouteGuard({ session }: { session: Session }) {
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      currentLocation.pathname !== nextLocation.pathname && session.hasUnsaved(),
  )
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    let active = true
    void session.beforeLeave().then((saved) => {
      if (!active) return
      if (
        saved ||
        window.confirm('Your Moonfall progress could not be saved. Leave and lose unsaved changes?')
      )
        blocker.proceed()
      else blocker.reset()
    })
    return () => {
      active = false
    }
  }, [blocker, session])
  return null
}
export function MoonfallNavigationGuard({ session }: { session: Session }) {
  const router = useContext(UNSAFE_DataRouterContext)
  useEffect(() => {
    function unload(event: BeforeUnloadEvent) {
      if (session.hasUnsaved()) {
        event.preventDefault()
        event.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', unload)
    return () => window.removeEventListener('beforeunload', unload)
  }, [session])
  return router ? <RouteGuard session={session} /> : null
}
