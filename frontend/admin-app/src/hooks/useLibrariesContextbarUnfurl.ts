import { useLayoutEffect } from 'react'

/**
 * Libraries & scans pages no longer emit a sibling strip that needs collapsing.
 * Auto, Manual and Jobs share the Scan page; other destinations live in the LHN.
 * Kept as a no-op so App.tsx and tests can stay wired without rewriting Jinja
 * segments into unfurl menus.
 */
export function useLibrariesContextbarUnfurl(enabled: boolean) {
  useLayoutEffect(() => {
    void enabled
  }, [enabled])
}
