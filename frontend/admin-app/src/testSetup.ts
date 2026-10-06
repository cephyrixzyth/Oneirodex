import '@testing-library/jest-dom/vitest'

/** Node 26+ jsdom may omit Storage unless `--localstorage-file` is set. */
function installMemoryLocalStorage() {
  const store = new Map<string, string>()
  const memory = {
    getItem(key: string) {
      return store.has(String(key)) ? store.get(String(key)) : null
    },
    setItem(key: string, value: string) {
      store.set(String(key), String(value))
    },
    removeItem(key: string) {
      store.delete(String(key))
    },
    clear() {
      store.clear()
    },
    key(index: number) {
      return [...store.keys()][index] ?? null
    },
    get length() {
      return store.size
    },
  }
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    enumerable: true,
    get: () => memory,
  })
}

if (typeof window !== 'undefined') {
  let needsPolyfill = false
  try {
    const probe = '__od_ls_probe__'
    window.localStorage?.setItem(probe, '1')
    if (window.localStorage?.getItem(probe) !== '1') needsPolyfill = true
    window.localStorage?.removeItem(probe)
  } catch {
    needsPolyfill = true
  }
  if (needsPolyfill || !window.localStorage) installMemoryLocalStorage()
}

/**
 * Clear web storage between tests.
 *
 * `useWidgetOrder` persists panel arrangement to `localStorage`, and OpsPage
 * renders only the panels that order names — so a stored arrangement written by
 * one test decides what a later one can see. Vitest isolates jsdom per *file*,
 * which was enough until CI moved to Node 24: that runtime ships its own
 * `localStorage` global, which is not the jsdom one and does not get torn down
 * with it, so state started surviving across files.
 *
 * That is exactly how `OpsPage shows library watch off honestly` failed on CI
 * and passed locally — it counts the two places "Library watch" is written, and
 * a leaked order had dropped the Services panel that holds the second one.
 * Order-dependent suites fail by file ordering, which is not stable, so this
 * clears rather than relying on any one runtime's teardown.
 */
beforeEach(() => {
  globalThis.localStorage?.clear()
  globalThis.sessionStorage?.clear()
})

/**
 * jsdom does not implement window.matchMedia; the rail (GT-B2) uses it to tell
 * the mobile drawer from the desktop collapse. Defaults to desktop.
 */
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  })
}
