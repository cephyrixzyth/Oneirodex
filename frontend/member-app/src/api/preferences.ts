/**
 * Member preferences helpers.
 *
 * Theme tokens live in the volume-served `od-tokens.css` stylesheet. The shared
 * React preferences dialog and this debounced tile-size save both use the
 * same validated JSON endpoint. Full-page reloads are reserved for dialog
 * saves, where shell settings and volume-served styles need to refresh.
 */

import { putPreferences } from '@oneirodex/ui'
export async function savePreferences(partial: LooseProps) {
  const body: Record<string, string | number | boolean> = {}
  Object.entries(partial).forEach(([key, value]) => {
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      body[key] = value
    }
  })
  return putPreferences(body)
}

/**
 * The shell-known fields plus the one being changed.
 *
 * The JSON preferences API merges omitted fields with the stored values, so a
 * slider drag only needs the shell-known defaults plus its changed value.
 */
export function preferencesFromShell(shellConfig: LooseProps = {}, partial: LooseProps = {}) {
  return {
    items_per_page: shellConfig.perPage ?? 20,
    default_sort: shellConfig.defaultSort || 'name',
    default_sort_order: shellConfig.defaultSortOrder || 'asc',
    theme: shellConfig.theme || 'default',
    show_tile_titles: shellConfig.showTileTitles === false ? 'false' : 'true',
    ...partial,
  }
}

/**
 * Open the server-rendered preferences modal used by the SPA shells.
 *
 * Moved into `@oneirodex/ui` (PR-4 d) so the admin shell can open it without the
 * `@member` cross-app alias. Re-exported here so `CommandPalette` / `TopBar` and
 * their tests keep importing it from `../api/preferences`.
 */
export { openPreferencesModal } from '@oneirodex/ui'
