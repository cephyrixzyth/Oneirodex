/**
 * W20-4 Scan/match policy — field map shared with Backend GlobalSettings.
 *
 * API (expected):
 *   GET|PUT /api/admin/scan-match/config
 *
 * Soft-degrade: missing endpoint or missing keys hide those controls.
 * Never expose mega-lib / depth-3 family walk (product lock).
 */

import { getJson, putJson } from './adminApi'
import { errorText } from '../utils/errorText'

export const SCAN_MATCH_CONFIG_PATH = '/api/admin/scan-match/config'

export const PEEL_PROFILES = Object.freeze({
  CONSERVATIVE: 'conservative',
  AGGRESSIVE: 'aggressive',
})

/** Defaults aligned with oneirodex.utils.match_scoring when BE omits values. */
export const SCAN_MATCH_DEFAULTS = Object.freeze({
  propose_only_scan: false,
  dupe_title_threshold: 0.85,
  match_high_threshold: 0.92,
  match_ambiguous_gap: 0.08,
  peel_profile: PEEL_PROFILES.CONSERVATIVE,
})

/**
 * Known policy keys the UI can render. Safe variant toggles are optional —
 * only shown when Backend includes them in the payload.
 */
export const CORE_POLICY_KEYS = Object.freeze([
  'propose_only_scan',
  'dupe_title_threshold',
  'match_high_threshold',
  'match_ambiguous_gap',
  'peel_profile',
])

/** Optional BE-shipped toggles for Stage C safe variants (never mega-lib). */
export const SAFE_VARIANT_KEYS = Object.freeze([
  'enable_year_drop_variant',
  'enable_pack_peel_variant',
  'enable_edition_peel_variant',
  'enable_sequel_numeral_variant',
])

export const SAFE_VARIANT_LABELS = Object.freeze({
  enable_year_drop_variant: {
    label: 'Year-drop search variant',
    hint: 'Also search without a trailing (19xx|20xx) year token.',
  },
  enable_pack_peel_variant: {
    label: 'Pack / collection peel',
    hint: 'Keep full pack title and add peeled head as a search variant.',
  },
  enable_edition_peel_variant: {
    label: 'Edition peel',
    hint: 'Keep full edition string and add head without Complete/Collector noise.',
  },
  enable_sequel_numeral_variant: {
    label: 'Sequel numeral swap',
    hint: 'Bidirectional 2↔II / 3↔III style variants for sequels.',
  },
})

/** Keys we never render even if a rogue payload includes them. */
export const FORBIDDEN_UI_KEYS = Object.freeze([
  'mega_lib',
  'megaLib',
  'allow_mega_lib',
  'family_walk_depth',
  'familyWalkDepth',
  'depth_3_family_walk',
  'depth3FamilyWalk',
  'max_family_depth',
])

/**
 * True when a key is present on the payload (including null/false/0).
 * Used for soft-degrade: hide controls Backend has not rolled out yet.
 */
export function hasPolicyKey(payload: unknown, key: string): boolean {
  if (!payload || typeof payload !== 'object') return false
  if (FORBIDDEN_UI_KEYS.includes(key)) return false
  return Object.prototype.hasOwnProperty.call(payload, key)
}

/** Which core + safe-variant fields Backend exposed this load. */
export function exposedPolicyKeys(payload: unknown): string[] {
  const keys: string[] = []
  for (const key of CORE_POLICY_KEYS) {
    if (hasPolicyKey(payload, key)) keys.push(key)
  }
  for (const key of SAFE_VARIANT_KEYS) {
    if (hasPolicyKey(payload, key)) keys.push(key)
  }
  return keys
}

export function normalizePeelProfile(value: unknown): string {
  const raw = String(value || '')
    .trim()
    .toLowerCase()
  if (raw === PEEL_PROFILES.AGGRESSIVE) return PEEL_PROFILES.AGGRESSIVE
  if (raw === PEEL_PROFILES.CONSERVATIVE) return PEEL_PROFILES.CONSERVATIVE
  return PEEL_PROFILES.CONSERVATIVE
}

function clampUnit(value: unknown, fallback: number) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  if (n < 0) return 0
  if (n > 1) return 1
  return n
}

/**
 * Build editable form state from a GET payload.
 * Only copies keys Backend exposed (soft-degrade).
 */
export function formFromPayload(payload: unknown) {
  const src: any = payload && typeof payload === 'object' ? payload : {}
  const form: Record<string, unknown> = {}
  const exposed = exposedPolicyKeys(src)

  if (exposed.includes('propose_only_scan')) {
    form.propose_only_scan = Boolean(src.propose_only_scan)
  }
  if (exposed.includes('dupe_title_threshold')) {
    form.dupe_title_threshold = clampUnit(
      src.dupe_title_threshold,
      SCAN_MATCH_DEFAULTS.dupe_title_threshold,
    )
  }
  if (exposed.includes('match_high_threshold')) {
    form.match_high_threshold = clampUnit(
      src.match_high_threshold,
      SCAN_MATCH_DEFAULTS.match_high_threshold,
    )
  }
  if (exposed.includes('match_ambiguous_gap')) {
    form.match_ambiguous_gap = clampUnit(
      src.match_ambiguous_gap,
      SCAN_MATCH_DEFAULTS.match_ambiguous_gap,
    )
  }
  if (exposed.includes('peel_profile')) {
    form.peel_profile = normalizePeelProfile(src.peel_profile)
  }
  for (const key of SAFE_VARIANT_KEYS) {
    if (exposed.includes(key)) {
      form[key] = Boolean(src[key])
    }
  }
  return { form, exposed }
}

/** Body for PUT — only keys currently exposed/edited. */
export function bodyFromForm(form: any, exposedKeys?: string[]) {
  const body: Record<string, unknown> = {}
  const keys = Array.isArray(exposedKeys) ? exposedKeys : Object.keys(form || {})
  for (const key of keys) {
    if (FORBIDDEN_UI_KEYS.includes(key)) continue
    if (!Object.prototype.hasOwnProperty.call(form, key)) continue
    if (key === 'peel_profile') {
      body.peel_profile = normalizePeelProfile(form.peel_profile)
      continue
    }
    if (
      key === 'dupe_title_threshold' ||
      key === 'match_high_threshold' ||
      key === 'match_ambiguous_gap'
    ) {
      body[key] = clampUnit(form[key], SCAN_MATCH_DEFAULTS[key])
      continue
    }
    if (key === 'propose_only_scan' || SAFE_VARIANT_KEYS.includes(key)) {
      body[key] = Boolean(form[key])
      continue
    }
  }
  return body
}

/**
 * Load config. Returns { ok, form, exposed, degradeReason }.
 * ok=false → soft-degrade (404 / network / empty).
 */
export async function loadScanMatchConfig() {
  try {
    const data = await getJson(SCAN_MATCH_CONFIG_PATH)
    const { form, exposed } = formFromPayload(data)
    if (!exposed.length) {
      return {
        ok: false,
        form: {},
        exposed: [],
        degradeReason: 'Scan/match settings are unavailable.',
      }
    }
    return { ok: true, form, exposed, degradeReason: null, raw: data }
  } catch (err) {
    const message = errorText(err) || String(err)
    return {
      ok: false,
      form: {},
      exposed: [],
      degradeReason:
        message.includes('404') || message.toLowerCase().includes('not found')
          ? 'Scan/match settings are unavailable. Configure propose-only scanning in Server Settings.'
          : `Could not load scan/match settings (${message}).`,
    }
  }
}

export async function saveScanMatchConfig(form: Record<string, unknown>, exposedKeys?: string[]) {
  const body = bodyFromForm(form, exposedKeys)
  return putJson(SCAN_MATCH_CONFIG_PATH, body)
}
