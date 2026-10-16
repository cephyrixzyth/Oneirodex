// Barrel for `@oneirodex/ui` — the one home for infrastructure the three SPAs
// (member-app, admin-app, ops-glance) all need.
//
// Wave B1.1 made `frontend/shared` a valid npm workspace package. Wave B1.2
// moves the real implementations here — one canonical copy of each module that
// had drifted into 2-3 divergent copies across the SPAs — and repoints every
// consumer onto `import { X } from '@oneirodex/ui'`.
//
// Phase 3.3 converted the package to TypeScript (`strict: true`); the exports
// carry types now and a consuming SPA's bundler compiles the source directly.
//
// Behavioural rule when copies diverged: the superset wins, so consolidating
// widens the narrow copies and narrows none.

export * from './confirmDialog.js'
export * from './libraryScanNotify.js'
export * from './toastStack.js'
export * from './useRailState.js'
export * from './csrf.js'
export * from './authApi.js'
export * from './envelopeError.js'
export * from './loadingStatusText.js'
export * from './toast.js'
export * from './platformSkins.js'
export * from './railIconsEra.js'
export * from './pageStatus.js'
export * from './Button.js'
export * from './Modal.js'
export * from './DataTable.js'
export * from './FilterChipGroup.js'
export * from './formIgnore.js'
export * from './railIcons.js'
export * from './useResource.js'
export * from './ViewerContext.js'
export * from './ShellConfigContext.js'
// PR-4 (d): AccountModal + its data helpers move here so the admin shell drops
// its `@member` cross-app alias. member-app keeps thin re-export shims at the
// old `api/tokens` / `utils/copyText` paths and re-exports openPreferencesModal
// from `api/preferences`.
export * from './copyText.js'
export * from './accountApi.js'
export * from './tokensApi.js'
export * from './preferencesModalHost.js'
export * from './PreferencesModal.js'
export * from './preferencesApi.js'
export * from './AccountModal.js'
export { sharedIconAliases } from './generatedIconPaths.js'

export * from './useTopBarReserve.js'
