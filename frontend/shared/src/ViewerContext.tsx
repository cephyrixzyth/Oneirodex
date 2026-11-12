import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { AuthSessionBoundary } from './AuthSessionBoundary.js'

/**
 * Viewer identity + role predicates — `@oneirodex/ui`.
 *
 * Wave B1.6. member-app used to thread one `shellConfig` object from `main`
 * through `<App>`, `Layout` and into every one of 40+ routed pages as a prop,
 * and each call site re-derived `Boolean(shellConfig.isAdmin)` /
 * `shellConfig.role || 'user'` for itself. This context carries the *identity*
 * half of that bootstrap once, with the predicates derived here so no caller
 * has to spell the coercion again.
 *
 * The rest of the bootstrap (perPage, tileSize, counts, currentFilters, feature
 * toggles) is the ShellConfig context's job — see `ShellConfigContext.tsx`.
 * Identity is split out because far more components need "is this an admin"
 * than need "how many tiles per page", and a component that only asks the
 * former should not re-render when a filter changes.
 */

/** Raw identity slice off the SPA root config / bootstrap object. */
export interface ViewerConfig {
  userId?: number | string | null
  role?: string
  isAdmin?: boolean
  isLibrarian?: boolean
  locale?: string
}

/** Normalised viewer — identity plus the derived role predicates. */
export interface Viewer {
  userId: number | string | null
  role: string
  isAdmin: boolean
  isLibrarian: boolean
  isChild: boolean
  locale: string
}

const MISSING = Symbol('ViewerContext.missing')

const ViewerContext = createContext<Viewer | typeof MISSING>(MISSING)

/**
 * Normalise a raw shell/bootstrap object into the viewer shape. Exported so
 * the SPA `main` entry can build the provider value from the parsed root
 * config and so tests can construct a viewer without knowing the derivation
 * rules.
 *
 * `isChild` has no dedicated flag on the shell yet — it is the role name today
 * and stays derived here so callers converge on one spelling the moment the
 * backend grows the flag.
 */
export function viewerFromConfig(config: ViewerConfig = {}): Viewer {
  const role = config.role || 'user'
  return {
    userId: config.userId ?? null,
    role,
    isAdmin: Boolean(config.isAdmin) || role === 'admin',
    isLibrarian: Boolean(config.isLibrarian) || role === 'librarian',
    isChild: role === 'child',
    locale: config.locale || 'en',
  }
}

export interface ViewerProviderProps {
  value?: ViewerConfig
  children?: ReactNode
}

export function ViewerProvider({ value, children }: ViewerProviderProps) {
  // Accept either an already-normalised viewer or a raw shell slice; memoise so
  // a stable `value` prop does not remake the object every render.
  const viewer = useMemo(() => viewerFromConfig(value), [value])
  return (
    <AuthSessionBoundary>
      <ViewerContext.Provider value={viewer}>{children}</ViewerContext.Provider>
    </AuthSessionBoundary>
  )
}

export function useViewer(): Viewer {
  const viewer = useContext(ViewerContext)
  if (viewer === MISSING) {
    throw new Error('useViewer must be used within a <ViewerProvider>')
  }
  return viewer
}
