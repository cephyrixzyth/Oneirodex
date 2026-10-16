/** Kind chip toggles for library browse (maps to /browse_games item_kind). */

import { ITEM_KINDS, ITEM_KIND_LABEL, ITEM_KIND_LABEL_PLURAL } from '../utils/itemKind'
import { FilterChipGroup } from '@oneirodex/ui'

/** Chips shown in the Library Kind filter row. */
export const ITEM_KIND_FILTER_CHIPS = ITEM_KINDS.map((kind) => ({
  kind,
  label: ITEM_KIND_LABEL_PLURAL[kind],
  title: ITEM_KIND_LABEL[kind],
}))

const KIND_ALIASES: Record<string, string> = Object.freeze({
  game: 'game',
  games: 'game',
  experience: 'experience',
  experiences: 'experience',
  'soft title': 'experience',
  soft_title: 'experience',
  'soft-title': 'experience',
  softtitles: 'experience',
  'soft titles': 'experience',
  emulator: 'emulator',
  emulators: 'emulator',
  emu: 'emulator',
  tool: 'tool',
  tools: 'tool',
  utility: 'tool',
  utilities: 'tool',
})

/**
 * Normalize a raw kind token to a canonical ITEM_KINDS value, or null.
 * @param {string} raw
 * @returns {'game' | 'experience' | 'emulator' | 'tool' | null}
 */
export function normalizeItemKindToken(raw: any) {
  const key = String(raw || '')
    .trim()
    .toLowerCase()
  return KIND_ALIASES[key] ?? null
}

/**
 * Parse an item_kind / content_kind filter value into canonical kinds (stable order).
 * @param {string | null | undefined} value
 * @returns {Array<'game' | 'experience' | 'emulator' | 'tool'>}
 */
export function parseItemKindFilter(value: any) {
  if (value == null || value === '') {
    return []
  }
  const seen = new Set()
  const kinds = []
  for (const part of String(value).split(',')) {
    const kind = normalizeItemKindToken(part)
    if (kind && !seen.has(kind)) {
      seen.add(kind)
      kinds.push(kind)
    }
  }
  return ITEM_KINDS.filter((kind) => seen.has(kind))
}

/**
 * Format selected kinds as a comma-joined browse param, or '' when empty (omit).
 * @param {Iterable<string>} kinds
 * @returns {string}
 */
export function formatItemKindFilter(kinds: any) {
  const selected = new Set(parseItemKindFilter([...kinds].join(',')))
  return ITEM_KINDS.filter((kind) => selected.has(kind)).join(',')
}

/**
 * @param {URLSearchParams} searchParams
 * @returns {Record<string, string>}
 */
export function itemKindFromSearchParams(searchParams: any) {
  const raw = searchParams.get('item_kind') ?? searchParams.get('content_kind')
  const formatted = formatItemKindFilter(parseItemKindFilter(raw))
  return formatted ? { item_kind: formatted } : {}
}

/**
 * Toggle a kind in the multi-select item_kind filter and apply via onApply.
 * Empty selection omits the param (all kinds).
 * @param {object} filters
 * @param {'game' | 'experience' | 'emulator' | 'tool'} kind
 * @param {(next: object) => void} onApply
 * @param {(filters: object) => object} cleanFilters
 */
export function toggleItemKindFilter(filters: any, kind: any, onApply: any, cleanFilters: any) {
  const canonical = normalizeItemKindToken(kind)
  if (!canonical) {
    onApply(cleanFilters({ ...filters }))
    return
  }
  const current = new Set(parseItemKindFilter(filters.item_kind))
  if (current.has(canonical)) {
    current.delete(canonical)
  } else {
    current.add(canonical)
  }
  const next = { ...filters }
  const formatted = formatItemKindFilter(current)
  if (formatted) {
    next.item_kind = formatted
  } else {
    delete next.item_kind
  }
  delete next.content_kind
  onApply(cleanFilters(next))
}

export function ItemKindFilterChips({
  filters,
  onApply,
  cleanFilters,
  t = (key: any) => key,
}: LooseProps) {
  const selected = parseItemKindFilter(filters.item_kind)
  const applySelection = (values: string[]) => {
    const next = { ...filters }
    const formatted = formatItemKindFilter(values)
    if (formatted) next.item_kind = formatted
    else delete next.item_kind
    delete next.content_kind
    onApply(cleanFilters(next))
  }

  return (
    <FilterChipGroup
      label={t('Kind filters')}
      options={ITEM_KIND_FILTER_CHIPS.map((chip) => ({
        value: chip.kind,
        label: t(chip.label),
        title: t(chip.title),
      }))}
      value={selected}
      onChange={applySelection}
      size="compact"
      className="od-badge-filter-chips"
    />
  )
}
