import { Component, type ErrorInfo, type ReactNode } from 'react'
import './AppErrorBoundary.css'

interface AppErrorBoundaryProps {
  children: ReactNode
  onReload?: () => void
}

interface AppErrorBoundaryState {
  failed: boolean
}

/** Contains render and lazy-chunk failures without automatic reload loops. */
export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = { failed: false }

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { failed: true }
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // Do not send component stacks or user data to a remote telemetry service.
  }

  private reload = () => {
    if (this.props.onReload) {
      this.props.onReload()
      return
    }
    window.location.reload()
  }

  render() {
    if (this.state.failed) {
      return (
        <main className="od-app-error">
          <section className="od-app-error__card" role="alert" aria-labelledby="od-app-error-title">
            <h1 id="od-app-error-title">Oneirodex hit a problem</h1>
            <p>The page could not finish loading. Reload Oneirodex to try again.</p>
            <button type="button" className="od-btn od-btn--primary" onClick={this.reload}>
              Reload Oneirodex
            </button>
          </section>
        </main>
      )
    }
    return this.props.children
  }
}

export default AppErrorBoundary
