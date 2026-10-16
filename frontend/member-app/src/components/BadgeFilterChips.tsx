/** Badge chip toggles for library browse (maps to /browse_games badge params). */

import { FilterChipGroup } from '@oneirodex/ui'

/** Chips shown in the Library LHN panel. VR is tile badge-only — not a filter chip. */
export const BADGE_FILTER_CHIPS = [
  { param: 'has_updates', label: 'Update', title: 'Updates available' },
  { param: 'path_missing', label: 'Missing', title: 'Removed from disk' },
  { param: 'new_import', label: 'New', title: 'Newly added to library' },
  {
    param: 'needs_translation',
    label: 'Lang',
    title: 'ROM language may not match your preferred game language',
  },
]

/**
 * URL/API badge params still recognized (includes legacy deep-links).
 * freshness_behind / recent_release stay parseable for old URLs but have no chip
 * after OUT/~ / RELEASE retirement (2026-08-01).
 */
export const BADGE_FILTER_PARAMS = [
  'is_vr',
  'freshness_behind',
  'recent_release',
  ...BADGE_FILTER_CHIPS.map((chip) => chip.param),
]

/**
 * @param {URLSearchParams} searchParams
 * @returns {Record<string, string>}
 */
export function badgeFiltersFromSearchParams(searchParams: any) {
  const next: Record<string, string> = {}
  for (const param of BADGE_FILTER_PARAMS) {
    const value = searchParams.get(param)
    if (value === '1' || value === 'true' || value === 'yes') {
      next[param] = '1'
    }
  }
  return next
}

/**
 * Toggle a badge filter param and apply via onApply(cleanFilters(...)).
 * @param {object} filters
 * @param {string} param
 * @param {(next: object) => void} onApply
 * @param {(filters: object) => object} cleanFilters
 */
export function toggleBadgeFilter(filters: any, param: any, onApply: any, cleanFilters: any) {
  const active = filters[param] === '1'
  const next = { ...filters }
  if (active) {
    delete next[param]
  } else {
    next[param] = '1'
  }
  onApply(cleanFilters(next))
}

export function BadgeFilterChips({
  filters,
  onApply,
  cleanFilters,
  t = (key: any) => key,
}: LooseProps) {
  const value = BADGE_FILTER_CHIPS.filter((chip) => filters[chip.param] === '1').map(
    (chip) => chip.param,
  )

  const applySelection = (nextValue: string[]) => {
    const selected = new Set(nextValue)
    const next = { ...filters }
    for (const chip of BADGE_FILTER_CHIPS) {
      if (selected.has(chip.param)) next[chip.param] = '1'
      else delete next[chip.param]
    }
    onApply(cleanFilters(next))
  }

  return (
    <FilterChipGroup
      label={t('Badge filters')}
      options={BADGE_FILTER_CHIPS.map((chip) => ({
        value: chip.param,
        label: t(chip.label),
        title: t(chip.title),
      }))}
      value={value}
      onChange={applySelection}
      size="compact"
      className="od-badge-filter-chips"
    />
  )
}
