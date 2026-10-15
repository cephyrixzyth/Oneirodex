/** Propose / import leaf libraries API helpers (preview-only; never auto-create). */

import { csrfHeaders, getJson, postForm, postJsonResult } from './adminApi'

export const PROPOSE_LEAF_URL = '/api/library_tools/propose_leaf_libraries'
export const IMPORT_LEAF_PREVIEW_URL = '/api/library_tools/import_leaf_libraries/preview'
export const LIBRARY_CREATE_URL = '/api/admin/libraries'
export const LIBRARY_SCAN_URL = '/api/admin/libraries/scan'

/** One normalized candidate row (propose or import preview). */
export interface CandidateRow {
  id: string
  path: string
  suggested_name: string
  platform: string
  scan_mode: 'files' | 'folders'
  scan_depth: 1 | 2
  reason: string
  source_index: number
}

/** One rejected row from an import preview. */
export interface ImportPreviewError {
  index: number | null
  path: string | null
  code: string
  message: string
  id: string
}

/** Normalized propose API payload. */
export interface ProposeResponse {
  root: string
  candidates: CandidateRow[]
  count: number
  autoCreate: boolean
}

/** Normalized import preview payload. */
export interface ImportPreviewResponse {
  candidates: CandidateRow[]
  errors: ImportPreviewError[]
  count: number
  errorCount: number
  autoCreate: boolean
  createHint: string
}

/** Soft-degrade / error shape returned by the propose + import preview fetchers. */
export interface ProposeLeafError {
  unavailable?: boolean
  error: string
}

/**
 * Normalize one candidate row (propose or import preview).
 */
export function normalizeCandidateRow(row: unknown, index: number): CandidateRow | null {
  if (!row || typeof row !== 'object') return null
  const r = row as Record<string, unknown>
  const path = String(r.path || '').trim()
  if (!path) return null
  const sourceIndex =
    typeof r.source_index === 'number' && Number.isFinite(r.source_index) ? r.source_index : index
  return {
    id: `${path}::${sourceIndex}`,
    path,
    suggested_name: String(r.suggested_name || r.name || path).trim() || path,
    platform: String(r.platform || 'OTHER').trim() || 'OTHER',
    scan_mode: r.scan_mode === 'files' ? 'files' : 'folders',
    scan_depth: Number(r.scan_depth) === 2 ? 2 : 1,
    reason: String(r.reason || '').trim(),
    source_index: sourceIndex,
  }
}

/**
 * Normalize propose API payload into a stable candidate list.
 */
export function normalizeProposeResponse(data: unknown): ProposeResponse {
  if (!data || typeof data !== 'object') {
    return { root: '', candidates: [], count: 0, autoCreate: false }
  }
  const d = data as Record<string, unknown>
  const raw = Array.isArray(d.candidates) ? d.candidates : []
  const candidates = raw
    .map((row: unknown, index: number) => normalizeCandidateRow(row, index))
    .filter((row): row is CandidateRow => row !== null)
  return {
    root: String(d.root || ''),
    candidates,
    count: typeof d.count === 'number' ? d.count : candidates.length,
    autoCreate: Boolean(d.auto_create),
  }
}

/**
 * Normalize import preview payload (candidates + errors; never creates).
 */
export function normalizeImportPreviewResponse(data: unknown): ImportPreviewResponse {
  if (!data || typeof data !== 'object') {
    return {
      candidates: [],
      errors: [],
      count: 0,
      errorCount: 0,
      autoCreate: false,
      createHint: '',
    }
  }
  const d = data as Record<string, unknown>
  const raw = Array.isArray(d.candidates) ? d.candidates : []
  const candidates = raw
    .map((row: unknown, index: number) => normalizeCandidateRow(row, index))
    .filter((row): row is CandidateRow => row !== null)
  const errors: ImportPreviewError[] = (Array.isArray(d.errors) ? d.errors : [])
    .filter((err: unknown): err is Record<string, unknown> => !!err && typeof err === 'object')
    .map((err: Record<string, unknown>, index: number) => ({
      index: typeof err.index === 'number' ? err.index : null,
      path: err.path != null ? String(err.path) : null,
      code: String(err.code || '').trim(),
      message: String(err.message || err.error || '').trim() || 'Row rejected',
      id: `err-${String(err.index ?? index)}-${String(err.code || 'unknown')}`,
    }))
  return {
    candidates,
    errors,
    count: typeof d.count === 'number' ? d.count : candidates.length,
    errorCount: typeof d.error_count === 'number' ? d.error_count : errors.length,
    autoCreate: Boolean(d.auto_create),
    createHint: String(d.create_hint || '').trim(),
  }
}

/**
 * Call propose API. Soft-degrades on 404 mid-rollout.
 * @returns {Promise<ProposeResponse | ProposeLeafError>}
 */
export async function fetchProposeLeafLibraries(
  root: string,
): Promise<ProposeResponse | ProposeLeafError> {
  const trimmed = String(root || '').trim()
  if (!trimmed) {
    return { error: 'Enter a root path under an allowed base.' }
  }

  const response = await fetch(PROPOSE_LEAF_URL, {
    method: 'POST',
    credentials: 'same-origin',
    headers: csrfHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ root: trimmed }),
  })

  if (response.status === 401) {
    window.location.href = '/login'
    throw new Error('unauthorized')
  }

  if (response.status === 404) {
    return {
      unavailable: true,
      error:
        'Propose leaf libraries API is not available on this build yet. Redeploy after the Backend W20-1 route lands.',
    }
  }

  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    return {
      error: data.message || data.error || `Propose failed (${response.status})`,
    }
  }

  const normalized = normalizeProposeResponse(data)
  if (normalized.autoCreate) {
    // Defense: UI never trusts an auto-create claim from older/buggy builds.
    return {
      error: 'Server reported auto_create — refusing. Propose must never create libraries.',
    }
  }
  return normalized
}

export interface ImportLeafPreviewOpts {
  /** 'json' | 'csv' | 'file'; anything else is treated as 'json'. */
  mode?: string
  text?: string
  file?: File | null
}

/**
 * Preview CSV/JSON leaf library import. Soft-degrades on 404; never creates.
 *
 * @returns {Promise<ImportPreviewResponse | ProposeLeafError>}
 */
export async function fetchImportLeafLibrariesPreview(
  opts: ImportLeafPreviewOpts,
): Promise<ImportPreviewResponse | ProposeLeafError> {
  const mode = opts?.mode || 'json'
  let response

  if (mode === 'file') {
    const file = opts?.file
    if (!file) {
      return { error: 'Choose a .json or .csv file to preview.' }
    }
    const form = new FormData()
    form.append('file', file, file.name || 'import.json')
    const name = String(file.name || '').toLowerCase()
    if (name.endsWith('.csv')) {
      form.append('format', 'csv')
    }
    response = await fetch(IMPORT_LEAF_PREVIEW_URL, {
      method: 'POST',
      credentials: 'same-origin',
      headers: csrfHeaders(),
      body: form,
    })
  } else if (mode === 'csv') {
    const text = String(opts?.text || '')
    if (!text.trim()) {
      return { error: 'Paste CSV with a header row (path, platform, …).' }
    }
    const form = new FormData()
    form.append('csv', text)
    response = await fetch(IMPORT_LEAF_PREVIEW_URL, {
      method: 'POST',
      credentials: 'same-origin',
      headers: csrfHeaders(),
      body: form,
    })
  } else {
    const text = String(opts?.text || '').trim()
    if (!text) {
      return { error: 'Paste a JSON array (or {candidates: […]}) to preview.' }
    }
    let body
    try {
      body = JSON.parse(text)
    } catch {
      return { error: 'Paste valid JSON (array or object with candidates/items/libraries/rows).' }
    }
    response = await fetch(IMPORT_LEAF_PREVIEW_URL, {
      method: 'POST',
      credentials: 'same-origin',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    })
  }

  if (response.status === 401) {
    window.location.href = '/login'
    throw new Error('unauthorized')
  }

  if (response.status === 404) {
    return {
      unavailable: true,
      error:
        'Import leaf libraries preview API is not available on this build yet. Redeploy after the Backend W20-1b route lands.',
    }
  }

  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    return {
      error: data.message || data.error || `Import preview failed (${response.status})`,
    }
  }

  const normalized = normalizeImportPreviewResponse(data)
  if (normalized.autoCreate) {
    return {
      error: 'Server reported auto_create — refusing. Import preview must never create libraries.',
    }
  }
  return normalized
}

/**
 * Create one library through the validated admin API.
 * @returns {Promise<{ ok: boolean, library_uuid?: string, error?: string }>}
 */
export async function createLibraryFromCandidate(
  candidate: CandidateRow,
): Promise<{ ok: boolean; library_uuid?: string; error?: string }> {
  const form = new FormData()
  form.append('name', candidate.suggested_name)
  form.append('platform', candidate.platform || 'OTHER')
  form.append('scan_depth', String(candidate.scan_depth || 1))
  form.append('watch_enabled', 'default')
  const created = await postForm<{ library_uuid?: string }>(LIBRARY_CREATE_URL, form)
  const libraryUuid = typeof created?.library_uuid === 'string' ? created.library_uuid : ''
  if (!libraryUuid) {
    return { ok: false, error: 'Library was created but its ID was not returned.' }
  }
  return { ok: true, library_uuid: libraryUuid }
}

export interface QueueLeafScanOpts {
  uuid: string
  path: string
  scan_mode: string
}

/**
 * Queue a first scan so last_scan_folder remembers the leaf path.
 */
export async function queueLeafScan({ uuid, path, scan_mode }: QueueLeafScanOpts) {
  const { ok, status, data } = await postJsonResult(LIBRARY_SCAN_URL, {
    library_uuid: uuid,
    folder: path,
    scan_mode: scan_mode === 'files' ? 'files' : 'folders',
    queue_policy: 'queue',
    force_parallel: false,
  })
  if (!ok) {
    const body = (data ?? {}) as Record<string, unknown>
    return {
      ok: false,
      error: String(body.message || body.error || `Scan queue failed (${status})`),
    }
  }
  return { ok: true, data }
}

export interface LeafCreateResult {
  path: string
  name: string
  uuid?: string
  ok: boolean
  stage: 'create' | 'scan'
  error?: string
  note?: string
}

/**
 * Confirm path: create each selected library, then queue a first scan when UUID is found.
 * Never invents a mega-lib — one create per candidate.
 * @returns {Promise<{ results: LeafCreateResult[], created: number, scanned: number, failed: number }>}
 */
export async function confirmCreateSelected(selected: CandidateRow[]) {
  const results: LeafCreateResult[] = []
  let created = 0
  let scanned = 0
  let failed = 0

  for (const candidate of selected) {
    const create = await createLibraryFromCandidate(candidate)
    if (!create.ok) {
      failed += 1
      results.push({
        path: candidate.path,
        name: candidate.suggested_name,
        ok: false,
        stage: 'create',
        error: create.error,
      })
      continue
    }
    created += 1

    const uuid = create.library_uuid || null
    if (!uuid) {
      results.push({
        path: candidate.path,
        name: candidate.suggested_name,
        ok: true,
        stage: 'create',
        note: 'Created. Could not resolve UUID to queue a first scan — use Scan management with this path.',
      })
      continue
    }

    const scan = await queueLeafScan({
      uuid,
      path: candidate.path,
      scan_mode: candidate.scan_mode,
    })
    if (scan.ok) {
      scanned += 1
      results.push({
        path: candidate.path,
        name: candidate.suggested_name,
        uuid,
        ok: true,
        stage: 'scan',
        note: 'Created and queued first scan.',
      })
    } else {
      results.push({
        path: candidate.path,
        name: candidate.suggested_name,
        uuid,
        ok: true,
        stage: 'create',
        note: `Created. Scan not queued: ${scan.error}`,
      })
    }
  }

  return { results, created, scanned, failed }
}
