import { fileIcons as importedFileIcons } from './config/file_type_icons.js';
import {
    detectLeafType,
    detectPlatformMismatch,
    formatPlatformMismatchTitle,
    isGarbageScaffolding,
} from './unmatchedTriage.js';
import {
    hasStageEHints,
    normalizeStageECandidates,
    normalizeStageEMeta,
    stageEChipSources,
    stageEMatchModeLabel,
    stageESourceLabel,
} from './stageECandidates.js';
import {
    scanJobsPollMs,
    scanJobsProgressSignature,
    scanJobsStructureSignature,
    unmatchedFoldersSignature,
} from './scanJobsDom.js';

const fileIcons = importedFileIcons || { default: 'fa-file' };

var currentPathAuto = '';
var currentPathManual = '';

function showSpinner() {
    var el = document.getElementById('globalSpinner');
    if (!el) return;
    el.style.display = 'flex';
    el.setAttribute('aria-busy', 'true');
    if (window.GtLoadingMotifs) {
        window.GtLoadingMotifs.mount(el, { size: 'lg' });
    }
}

function hideSpinner() {
    var el = document.getElementById('globalSpinner');
    if (!el) return;
    el.style.display = 'none';
    el.setAttribute('aria-busy', 'false');
}

function escapeHtml(value) {
    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/** Machine codes from duplicate_check / scan → one-line librarian copy. */
const UNMATCHED_MATCH_REASON_LABELS = {
    same_path: 'Same on-disk path as an existing library game.',
    title_vs_folder: 'Folder title closely matches an existing library game folder.',
    title_vs_library_name: 'Folder title closely matches an existing library game name.',
    title_below_threshold:
        'IGDB hit exists, but the folder title differs too much to auto-mark as duplicate.',
};

const UNMATCHED_STATUS_FALLBACK = {
    Duplicate:
        'Another library game already uses this IGDB match and the folder title looks like the same game.',
    Unmatched:
        'Could not auto-match to IGDB (or IGDB already used by a different-titled folder).',
    Ignore: 'Folder is ignored and will not be scanned.',
    Pending: 'Awaiting classification.',
};

/**
 * One-line “why unmatched?” explainer. Prefers Backend why_unmatched /
 * unmatched_reason; else match_reason + suggested_kind*. Null-safe.
 */
function formatWhyUnmatched(folder) {
    if (!folder || typeof folder !== 'object') return '';

    const summary =
        (folder.why_unmatched != null && String(folder.why_unmatched).trim()) ||
        (folder.unmatched_reason != null && String(folder.unmatched_reason).trim()) ||
        '';
    if (summary) return summary;

    const rawReason = folder.match_reason == null ? '' : String(folder.match_reason).trim();
    let reason = '';
    if (rawReason) {
        const code = rawReason.toLowerCase();
        reason = UNMATCHED_MATCH_REASON_LABELS[code] || rawReason;
    }

    const suggestedRaw = folder.suggested_kind == null
        ? ''
        : String(folder.suggested_kind).trim().toLowerCase();
    const suggestedKind = ['experience', 'emulator', 'tool', 'game'].includes(suggestedRaw)
        ? suggestedRaw
        : '';
    const suggestedLabel =
        (folder.suggested_kind_label != null && String(folder.suggested_kind_label).trim()) ||
        (suggestedKind === 'experience'
            ? 'Soft title'
            : suggestedKind === 'emulator'
                ? 'Emulator'
                : suggestedKind === 'tool'
                    ? 'Utility'
                    : suggestedKind === 'game'
                        ? 'Game'
                        : '');
    const candidate = folder.suggested_candidate_name == null
        ? ''
        : String(folder.suggested_candidate_name).trim();

    if (suggestedLabel) {
        const hint = candidate
            ? `Scan suggests cataloging as ${suggestedLabel} (e.g. ${candidate}).`
            : `Scan suggests cataloging as ${suggestedLabel}.`;
        if (reason) return `${reason} ${hint}`;
        if (folder.status === 'Unmatched' || folder.status === 'Pending') {
            return `No IGDB game match. ${hint}`;
        }
        return hint;
    }

    if (reason) return reason;
    if (folder.status && UNMATCHED_STATUS_FALLBACK[folder.status]) {
        return UNMATCHED_STATUS_FALLBACK[folder.status];
    }
    return '';
}

/**
 * Format Backend match_score beside Why unmatched?. Null-safe.
 * ≤1 → two decimals; 1–100 → whole/one decimal.
 */
function formatMatchScore(score) {
    if (score == null || score === '') return '';
    const n = Number(score);
    if (!Number.isFinite(n)) return '';
    if (n > 1 && n <= 100) {
        return Number.isInteger(n) ? String(n) : String(Math.round(n * 10) / 10);
    }
    return (Math.round(n * 100) / 100).toFixed(2);
}

/**
 * Ordered Stage A peel trail from Backend transforms[].
 * Soft-degrades when missing / mid-rollout — returns [].
 */
function normalizeTransforms(folder) {
    if (!folder || typeof folder !== 'object') return [];
    const raw = folder.transforms;
    if (!Array.isArray(raw) || raw.length === 0) return [];
    return raw
        .filter((step) => step && typeof step === 'object')
        .map((step) => ({
            stage: step.stage == null ? '' : String(step.stage).trim(),
            before: step.before == null ? '' : String(step.before),
            after: step.after == null ? '' : String(step.after),
            reason: step.reason == null ? '' : String(step.reason).trim(),
        }))
        .filter((step) => step.stage || step.before || step.after);
}

/** HTML for expandable name transform trail (stage · before → after · reason). */
function buildTransformTrailHtml(folder) {
    const steps = normalizeTransforms(folder);
    if (!steps.length) return '';
    const items = steps.map((step) => {
        const stage = escapeHtml(step.stage || '—');
        const before = escapeHtml(step.before);
        const after = escapeHtml(step.after);
        const reason = step.reason
            ? `<span class="unmatched-why__transform-reason">${escapeHtml(step.reason)}</span>`
            : '';
        return `<li class="unmatched-why__transform-step"><span class="unmatched-why__transform-stage">${stage}</span><span class="unmatched-why__transform-pair"><code>${before}</code> → <code>${after}</code></span>${reason}</li>`;
    }).join('');
    return `<details class="unmatched-why__transforms"><summary class="unmatched-why__transforms-summary">Name transform trail (${steps.length})</summary><ol class="unmatched-why__transform-list">${items}</ol></details>`;
}

/**
 * Quiet Stage E propose-only chip + expandable candidates (Moby / TheGamesDB).
 * Soft-degrades when list API has not flattened proposal fields yet.
 */
function buildStageEHtml(folder) {
    if (!hasStageEHints(folder)) return '';
    const candidates = normalizeStageECandidates(folder);
    const meta = normalizeStageEMeta(folder);
    const sources = stageEChipSources(candidates);
    const chipDetail = sources.length ? sources.join(' · ') : 'catalog';
    const title = escapeHtml(
        'Propose-only catalog hints after Stage D miss — not auto-matched. Use Fix search / Identify to apply.',
    );
    const chip = `<span class="unmatched-stage-e-chip" title="${title}">Stage E · propose only · ${escapeHtml(chipDetail)}</span>`;
    let body = '';
    if (candidates.length > 0) {
        const items = candidates.map((hit) => {
            const source = escapeHtml(stageESourceLabel(hit.source));
            const mode = stageEMatchModeLabel(hit.match_mode);
            const label = escapeHtml(hit.name || hit.id || 'Candidate');
            const nameHtml = hit.url
                ? `<a class="unmatched-stage-e__name" href="${escapeHtml(hit.url)}" target="_blank" rel="noopener noreferrer">${label}</a>`
                : `<span class="unmatched-stage-e__name">${label}</span>`;
            const modeHtml = mode
                ? `<span class="unmatched-stage-e__mode">${escapeHtml(mode)}</span>`
                : '';
            return `<li class="unmatched-stage-e__hit"><span class="unmatched-stage-e__source">${source}</span>${nameHtml}${modeHtml}</li>`;
        }).join('');
        body = `<details class="unmatched-stage-e__details"><summary class="unmatched-stage-e__summary">Stage E candidates (${candidates.length})</summary><p class="unmatched-stage-e__note">Catalog hints only — Identify to apply. Not auto-matched.</p><ul class="unmatched-stage-e__list">${items}</ul></details>`;
    } else if (meta) {
        const reason = escapeHtml(meta.match_reason || 'Stage E propose-only');
        body = `<p class="unmatched-stage-e__meta" title="${title}">${reason} — Identify to apply.</p>`;
    }
    return `<div class="unmatched-stage-e">${chip}${body}</div>`;
}

/** Basename of a folder path (null-safe). */
function unmatchedFolderBasename(path) {
    const parts = String(path || '')
        .replace(/\\/g, '/')
        .split('/')
        .filter(Boolean);
    return parts.length ? parts[parts.length - 1] : '';
}

/**
 * Soft Wave 17 naming: prefer search_name, else folder_name / basename.
 * Disk path is never renamed here — only Identify search prefill.
 */
function resolveUnmatchedSearchName(folder) {
    if (!folder || typeof folder !== 'object') return '';
    const soft =
        (folder.search_name != null && String(folder.search_name).trim()) ||
        (folder.display_name != null && String(folder.display_name).trim()) ||
        '';
    if (soft) return soft;
    if (folder.suggested_search_name != null && String(folder.suggested_search_name).trim()) {
        return String(folder.suggested_search_name).trim();
    }
    if (folder.folder_name != null && String(folder.folder_name).trim()) {
        return String(folder.folder_name).trim();
    }
    return unmatchedFolderBasename(folder.folder_path);
}

/**
 * Normalize matched library hit for side-by-side compare (list `matched_game` /
 * `duplicate_of`, flat matched_game_* fields, or /duplicates candidates).
 * Soft-reads size/date when Backend adds them — never invents values.
 */
function pickDiskSizeBytes(source) {
    if (!source || typeof source !== 'object') return null;
    const keys = ['size_bytes', 'folder_size_bytes', 'folder_size', 'size'];
    for (let i = 0; i < keys.length; i += 1) {
        const key = keys[i];
        if (source[key] == null || source[key] === '') continue;
        const n = Number(source[key]);
        if (Number.isFinite(n) && n >= 0) return n;
    }
    return null;
}

function pickDiskDate(source) {
    if (!source || typeof source !== 'object') return null;
    const keys = [
        'mtime',
        'folder_mtime',
        'modified_at',
        'date_modified',
        'failed_time',
        'date_identified',
        'date_created',
    ];
    for (let i = 0; i < keys.length; i += 1) {
        const key = keys[i];
        if (source[key] == null || source[key] === '') continue;
        const raw = source[key];
        if (typeof raw === 'number' && Number.isFinite(raw)) {
            const ms = raw < 1e12 ? raw * 1000 : raw;
            const d = new Date(ms);
            if (!Number.isNaN(d.getTime())) return d.toISOString();
            continue;
        }
        const text = String(raw).trim();
        if (!text) continue;
        const parsed = Date.parse(text);
        if (!Number.isNaN(parsed)) return new Date(parsed).toISOString();
        return text;
    }
    return null;
}

function formatByteSize(bytes) {
    if (bytes == null || bytes === '') return null;
    const n = Number(bytes);
    if (!Number.isFinite(n) || n < 0) return null;
    if (n < 1024) return `${Math.round(n)} B`;
    const units = ['KB', 'MB', 'GB', 'TB'];
    let value = n / 1024;
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
        value /= 1024;
        unit += 1;
    }
    const rounded = value >= 10 || unit === 0 ? Math.round(value) : Math.round(value * 10) / 10;
    return `${rounded} ${units[unit]}`;
}

function formatDiskDate(value) {
    if (value == null || value === '') return null;
    const text = String(value).trim();
    if (!text) return null;
    const parsed = Date.parse(text);
    if (Number.isNaN(parsed)) return text;
    try {
        return new Intl.DateTimeFormat(undefined, {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
        }).format(new Date(parsed));
    } catch (err) {
        return new Date(parsed).toISOString();
    }
}

function normalizeMatchedGame(folder) {
    if (!folder || typeof folder !== 'object') return null;
    const nested = folder.matched_game || folder.duplicate_of;
    if (nested && typeof nested === 'object') {
        const uuid = nested.uuid || nested.matched_game_uuid || null;
        const name = (nested.name || nested.title || '').trim();
        const path = nested.path || nested.full_disk_path || '';
        const cover = nested.cover_url || nested.cover || null;
        if (!name && !uuid && !path) return null;
        return {
            uuid: uuid || null,
            name: name || 'Library game',
            path: path || '',
            cover_url: cover || null,
            match_score: nested.match_score != null ? nested.match_score : folder.match_score,
            size_bytes: pickDiskSizeBytes(nested),
            mtime: pickDiskDate(nested),
        };
    }
    const flatName =
        (folder.matched_game_name != null && String(folder.matched_game_name).trim()) ||
        '';
    const flatPath =
        (folder.matched_game_path != null && String(folder.matched_game_path).trim()) ||
        '';
    const flatUuid = folder.matched_game_uuid || null;
    // uuid alone is not enough — leave null so callers soft-enrich from /duplicates
    if (!flatName && !flatPath) return null;
    return {
        uuid: flatUuid || null,
        name: flatName || 'Library game',
        path: flatPath,
        cover_url: folder.matched_game_cover_url || null,
        match_score: folder.match_score,
        size_bytes: pickDiskSizeBytes({
            size_bytes: folder.matched_game_size_bytes,
            size: folder.matched_game_size,
            folder_size_bytes: folder.matched_game_folder_size_bytes,
        }),
        mtime: pickDiskDate({
            mtime: folder.matched_game_mtime,
            folder_mtime: folder.matched_game_folder_mtime,
            modified_at: folder.matched_game_modified_at,
            date_identified: folder.matched_game_date_identified,
            date_created: folder.matched_game_date_created,
        }),
    };
}

function compareEmptyCell() {
    return `<span class="unmatched-dupe-compare__empty" title="Not provided by API yet">—</span>`;
}

function compareFieldHtml(label, innerHtml) {
    return `<div class="unmatched-dupe-compare__field"><dt>${escapeHtml(label)}</dt><dd>${innerHtml}</dd></div>`;
}

/**
 * Side-by-side folder vs library hit for Duplicate trail (path · size · date).
 * Soft-degrades when size/date omitted mid-rollout.
 */
function buildDupeOfHtml(folder) {
    const hit = normalizeMatchedGame(folder);
    const isDuplicate = folder && folder.status === 'Duplicate';
    if (!hit && !isDuplicate) return '';

    const folderName = escapeHtml(
        resolveUnmatchedSearchName(folder) ||
            unmatchedFolderBasename(folder.folder_path) ||
            'Folder',
    );
    const folderPath = folder.folder_path ? String(folder.folder_path) : '';
    const folderSize = formatByteSize(pickDiskSizeBytes(folder));
    const folderDate = formatDiskDate(pickDiskDate(folder));
    const folderPathHtml = folderPath
        ? `<button type="button" class="unmatched-dupe-of__path reveal-path-btn" data-path="${escapeHtml(folderPath)}" title="Open unmatched folder path">${escapeHtml(folderPath)}</button>`
        : compareEmptyCell();

    let libraryInner = `<p class="unmatched-dupe-compare__missing">No library hit yet</p>`;
    if (hit) {
        const score = formatMatchScore(hit.match_score != null ? hit.match_score : folder.match_score);
        const scoreChip = score
            ? `<span class="unmatched-why__score" title="Match confidence score">${escapeHtml(score)}</span>`
            : '';
        const thumb = hit.cover_url
            ? `<img class="unmatched-dupe-of__thumb" src="${escapeHtml(hit.cover_url)}" alt="" width="28" height="36" loading="lazy">`
            : `<span class="unmatched-dupe-of__thumb unmatched-dupe-of__thumb--empty" aria-hidden="true"></span>`;
        const title = escapeHtml(hit.name);
        const detailsHref = hit.uuid
            ? `/game_details/${encodeURIComponent(hit.uuid)}`
            : '';
        const titleHtml = detailsHref
            ? `<a class="unmatched-dupe-of__title" href="${detailsHref}" title="Open library game details">${title}</a>`
            : `<span class="unmatched-dupe-of__title">${title}</span>`;
        const pathHtml = hit.path
            ? `<button type="button" class="unmatched-dupe-of__path reveal-path-btn" data-path="${escapeHtml(hit.path)}" title="Open library game path">${escapeHtml(hit.path)}</button>`
            : compareEmptyCell();
        const sizeLabel = formatByteSize(hit.size_bytes);
        const dateLabel = formatDiskDate(hit.mtime);
        const uuidHtml = hit.uuid
            ? compareFieldHtml(
                'UUID',
                `<span class="unmatched-dupe-of__uuid" title="Library game UUID">${escapeHtml(hit.uuid)}</span>`,
            )
            : '';
        libraryInner = `
          <div class="unmatched-dupe-compare__head">
            ${thumb}
            <div class="unmatched-dupe-compare__head-text">
              <span class="unmatched-dupe-compare__role">Library game</span>
              ${titleHtml}
              ${scoreChip}
            </div>
          </div>
          <dl class="unmatched-dupe-compare__fields">
            ${compareFieldHtml('Path', pathHtml)}
            ${compareFieldHtml('Size', sizeLabel ? escapeHtml(sizeLabel) : compareEmptyCell())}
            ${compareFieldHtml('Date', dateLabel ? escapeHtml(dateLabel) : compareEmptyCell())}
            ${uuidHtml}
          </dl>`;
    }

    return `
      <div class="unmatched-dupe-compare" data-dupe-uuid="${escapeHtml((hit && hit.uuid) || '')}" role="group" aria-label="Duplicate side-by-side comparison">
        <div class="unmatched-dupe-compare__banner">
          <span class="unmatched-dupe-of__label">Compare</span>
          <span class="unmatched-dupe-compare__banner-text">Review folder and library details side by side</span>
          <button type="button" class="od-cbtn unmatched-dupe-compare__pop">Compare details</button>
        </div>
        <div class="unmatched-dupe-compare__grid">
          <div class="unmatched-dupe-compare__side unmatched-dupe-compare__side--folder">
            <div class="unmatched-dupe-compare__head">
              <div class="unmatched-dupe-compare__head-text">
                <span class="unmatched-dupe-compare__role">This folder</span>
                <span class="unmatched-dupe-of__title">${folderName}</span>
              </div>
            </div>
            <dl class="unmatched-dupe-compare__fields">
              ${compareFieldHtml('Path', folderPathHtml)}
              ${compareFieldHtml('Size', folderSize ? escapeHtml(folderSize) : compareEmptyCell())}
              ${compareFieldHtml('Date', folderDate ? escapeHtml(folderDate) : compareEmptyCell())}
            </dl>
          </div>
          <div class="unmatched-dupe-compare__side unmatched-dupe-compare__side--library${hit ? '' : ' unmatched-dupe-compare__side--empty'}">
            ${libraryInner}
          </div>
        </div>
      </div>`;
}

/**
 * Library-style upper-right toast (mirrors member/admin-app od-toast-host).
 * Exposes window.odShowAdminToast for admin_manage_libs.js.
 */
function showToast(message, variant) {
    if (!message) return;
    let host = document.getElementById('od-toast-host');
    if (!host) {
        host = document.createElement('div');
        host.id = 'od-toast-host';
        host.className = 'od-toast-host';
        host.setAttribute('aria-live', 'polite');
        document.body.appendChild(host);
    }
    const legacy = document.querySelector('.success-notification');
    if (legacy) legacy.remove();

    const toneRaw = String(variant || 'success');
    const tone =
        toneRaw === 'danger' || toneRaw === 'error'
            ? 'error'
            : toneRaw === 'warning' || toneRaw === 'warn'
              ? 'warn'
              : toneRaw === 'info'
                ? 'info'
                : 'success';
    const el = document.createElement('div');
    el.className = `od-toast od-toast--${tone}`;
    el.textContent = String(message);
    host.appendChild(el);
    window.setTimeout(() => {
        el.classList.add('od-toast--out');
        window.setTimeout(() => {
            el.remove();
            if (host && !host.childElementCount) host.remove();
        }, 220);
    }, 3500);
}
window.odShowAdminToast = showToast;

/** Field map expected from Backend scan-start / refresh_all once queue/force ships. */
const SCAN_QUEUE_POLICY = { QUEUE: 'queue', FORCE: 'force' };

function isScanBusyStatus(status) {
    return status === 'Running' || status === 'Stopping';
}

function isScanQueuedStatus(status) {
    const s = String(status || '').toLowerCase();
    return s === 'queued' || s === 'pending' || s === 'scheduled';
}

const SCAN_JOB_FILTER_KEY = 'od.scanJobs.filters';
const SCAN_JOB_STATUS_OPTIONS = [
    'Running',
    'Queued',
    'Completed',
    'Failed',
    'Cancelled',
    'Scheduled',
];

/** Soft-format seconds → "2m 14s" / "1h 5m" (no fake precision). */
function formatScanDurationSeconds(rawSeconds) {
    const n = Number(rawSeconds);
    if (!Number.isFinite(n) || n < 0) return '';
    const total = Math.floor(n);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    if (h > 0) {
        return m > 0 ? `${h}h ${m}m` : `${h}h`;
    }
    if (m > 0) {
        return s > 0 ? `${m}m ${s}s` : `${m}m`;
    }
    return `${s}s`;
}

function scanJobElapsedLabel(job) {
    if (!job) return '';
    if (job.elapsed_label) return String(job.elapsed_label);
    if (job.elapsed_seconds != null && job.elapsed_seconds !== '') {
        return formatScanDurationSeconds(job.elapsed_seconds);
    }
    return '';
}

function scanJobEtaLabel(job) {
    if (!job) return '';
    if (job.eta_label) return String(job.eta_label);
    if (job.eta_seconds != null && job.eta_seconds !== '') {
        const formatted = formatScanDurationSeconds(job.eta_seconds);
        return formatted ? `~${formatted} left` : '';
    }
    return '';
}

/** Compact timing line for job rows / running banner. Soft-degrade when fields absent. */
function scanJobTimingLine(job) {
    if (!job) return '';
    const status = String(job.status || '');
    const elapsed = scanJobElapsedLabel(job);
    const eta = scanJobEtaLabel(job);
    if (isScanQueuedStatus(status) && status.toLowerCase() !== 'scheduled') {
        // Queued: show queue-wait elapsed if Backend sends it; never invent ETA.
        return elapsed ? `Waited ${elapsed}` : '';
    }
    if (isScanBusyStatus(status)) {
        const parts = [];
        if (elapsed) parts.push(elapsed);
        if (eta) parts.push(eta);
        return parts.join(' · ');
    }
    return '';
}

function loadScanJobFilters() {
    const defaults = { statuses: [], library_uuid: '', q: '' };
    try {
        const raw = localStorage.getItem(SCAN_JOB_FILTER_KEY);
        if (!raw) return defaults;
        const parsed = JSON.parse(raw);
        const statuses = Array.isArray(parsed.statuses)
            ? parsed.statuses.filter((s) => SCAN_JOB_STATUS_OPTIONS.includes(s))
            : [];
        return {
            statuses,
            library_uuid: String(parsed.library_uuid || ''),
            q: String(parsed.q || ''),
        };
    } catch (_err) {
        return defaults;
    }
}

function saveScanJobFilters(filters) {
    try {
        localStorage.setItem(SCAN_JOB_FILTER_KEY, JSON.stringify({
            statuses: Array.isArray(filters.statuses) ? filters.statuses : [],
            library_uuid: String(filters.library_uuid || ''),
            q: String(filters.q || ''),
        }));
    } catch (_err) {
        /* ignore quota / private mode */
    }
}

function jobMatchesStatusFilter(job, statuses) {
    if (!statuses || !statuses.length) return true;
    const status = String(job.status || '');
    const cancelledByUser = status === 'Failed' && job.error_message === 'Scan cancelled by user';
    return statuses.some((wanted) => {
        if (wanted === 'Running') return status === 'Running' || status === 'Stopping';
        if (wanted === 'Queued') {
            const s = status.toLowerCase();
            return s === 'queued' || s === 'pending';
        }
        if (wanted === 'Scheduled') return status === 'Scheduled';
        if (wanted === 'Cancelled') return status === 'Cancelled' || cancelledByUser;
        if (wanted === 'Failed') return status === 'Failed' && !cancelledByUser;
        if (wanted === 'Completed') return status === 'Completed';
        return status === wanted;
    });
}

function filterScanJobsClientSide(jobs, filters) {
    const list = Array.isArray(jobs) ? jobs : [];
    const statuses = filters && filters.statuses ? filters.statuses : [];
    const libraryUuid = String((filters && filters.library_uuid) || '').trim();
    const q = String((filters && filters.q) || '').trim().toLowerCase();
    return list.filter((job) => {
        if (!jobMatchesStatusFilter(job, statuses)) return false;
        if (libraryUuid && String(job.library_uuid || '') !== libraryUuid) return false;
        if (q) {
            const path = String(job.scan_folder || '').toLowerCase();
            if (!path.includes(q)) return false;
        }
        return true;
    });
}

function buildScanJobsStatusUrl(filters) {
    const params = new URLSearchParams();
    if (filters.statuses && filters.statuses.length) {
        params.set('status', filters.statuses.join(','));
    }
    if (filters.library_uuid) params.set('library_uuid', filters.library_uuid);
    if (filters.q) params.set('q', filters.q);
    const qs = params.toString();
    return qs ? `/api/scan_jobs_status?${qs}` : '/api/scan_jobs_status';
}

/** Animate motif to the right of Start Scan while running or queued. */
function updateAutoScanStatusIcon(jobs) {
    const el = document.getElementById('autoScanStatus');
    if (!el) return;
    const list = Array.isArray(jobs) ? jobs : [];
    const busyJob = list.find((j) => isScanBusyStatus(j && j.status));
    const queuedJob = list.find((j) => isScanQueuedStatus(j && j.status));
    const busy = Boolean(busyJob);
    const queued = Boolean(queuedJob);
    const active = busy || queued;
    const label = el.querySelector('.auto-scan-status__label');
    const timingEl = el.querySelector('.auto-scan-status__timing');
    const motifHost = el.querySelector('.auto-scan-status__motif');
    if (!active) {
        el.hidden = true;
        el.dataset.state = 'idle';
        if (label) label.textContent = 'Idle';
        if (timingEl) {
            timingEl.hidden = true;
            timingEl.textContent = '';
        }
        return;
    }
    el.hidden = false;
    el.dataset.state = busy ? 'running' : 'queued';
    if (label) label.textContent = busy ? 'Scanning…' : 'Queued…';
    const timing = scanJobTimingLine(busyJob || queuedJob);
    if (timingEl) {
        if (timing) {
            timingEl.hidden = false;
            timingEl.textContent = timing;
        } else {
            timingEl.hidden = true;
            timingEl.textContent = '';
        }
    }
    if (motifHost && !motifHost.querySelector('.od-spinner, .od-loading-motif')) {
        // Remounting on every 3s poll tore the SVG down and restarted the
        // animation — that hitch stacked with the jobs-table rebuild.
        if (window.GtLoadingMotifs) {
            window.GtLoadingMotifs.mount(motifHost, { size: 'sm' });
        } else {
            motifHost.innerHTML = '<span class="od-spinner od-spinner--sm" aria-hidden="true"></span>';
        }
    }
}

function buildScanQueueRequestFields(policy) {
    const useForce = policy === SCAN_QUEUE_POLICY.FORCE;
    return {
        queue_policy: useForce ? SCAN_QUEUE_POLICY.FORCE : SCAN_QUEUE_POLICY.QUEUE,
        force_parallel: useForce,
    };
}

function isAlreadyRunningReject(httpStatus, body) {
    if (httpStatus === 409) return true;
    const status = String(body && body.status || '').toLowerCase();
    if (status === 'rejected') {
        const msg = `${(body && body.message) || ''} ${(body && body.error) || ''}`.toLowerCase();
        return msg.includes('already') || msg.includes('running') || msg.includes('in progress');
    }
    const err = `${(body && body.error) || (body && body.message) || ''}`.toLowerCase();
    return err.includes('already running') || err.includes('already in progress');
}

function isScanCoalesced(body) {
    if (!body) return false;
    if (body.coalesced === true) return true;
    if (Number(body.coalesced_count) > 0) return true;
    if (Array.isArray(body.jobs) && body.jobs.some((job) => job && job.coalesced === true)) {
        return true;
    }
    return false;
}

function toastForScanStartResponse(body, httpOk) {
    const status = String(body && body.status || '').toLowerCase();
    const message = String((body && (body.message || body.error)) || '').trim();
    const coalescedSuffix = isScanCoalesced(body) ? ' · coalesced' : '';
    if (status === 'queued') {
        const position = body && body.position != null
            ? body.position
            : (body && body.jobs && body.jobs[0] && body.jobs[0].position != null
                ? body.jobs[0].position
                : null);
        if (position != null) {
            return { text: `Queued · position ${position}${coalescedSuffix}`, variant: 'info' };
        }
        if (body && body.count != null) {
            return {
                text: message || `Queued · ${body.count} library refresh job(s)${coalescedSuffix}`,
                variant: 'info',
            };
        }
        return {
            text: message || `Queued · waiting for the current job to finish.${coalescedSuffix ? ' (coalesced)' : ''}`,
            variant: 'info',
        };
    }
    if (status === 'started') {
        const risk = String((body && body.risk) || '').trim();
        const base = message || 'Scan started.';
        return { text: risk ? `${base} ${risk}` : base, variant: risk ? 'warning' : 'success' };
    }
    if (status === 'rejected' || !httpOk) {
        return { text: message || (body && body.error) || 'Scan request was rejected.', variant: 'error' };
    }
    if (httpOk && (body && (body.count != null || Array.isArray(body.queued)))) {
        const count = body.count != null ? body.count : body.queued.length;
        return { text: message || `Queued · ${count} library refresh job(s)`, variant: 'info' };
    }
    if (httpOk) {
        return { text: message || 'Scan request accepted.', variant: 'success' };
    }
    return { text: message || (body && body.error) || 'Scan request failed.', variant: 'error' };
}

function ensureScanConflictModal() {
    let root = document.getElementById('odScanConflictModal');
    if (root) return root;
    root = document.createElement('div');
    root.id = 'odScanConflictModal';
    root.className = 'od-scan-conflict';
    root.hidden = true;
    root.setAttribute('role', 'dialog');
    root.setAttribute('aria-modal', 'true');
    root.setAttribute('aria-labelledby', 'odScanConflictTitle');
    root.innerHTML = `
        <div class="od-scan-conflict__panel" role="document">
            <div class="od-scan-conflict__toolbar">
                <h2 id="odScanConflictTitle" class="od-scan-conflict__title">Scan in progress</h2>
                <button type="button" class="od-scan-conflict__close" data-scan-conflict="cancel" aria-label="Close">×</button>
            </div>
            <p class="od-scan-conflict__lede">
                Another scan is already running. Queue this request (recommended) or force a parallel run.
            </p>
            <div class="od-scan-conflict__choices">
                <button type="button" class="btn btn-primary od-scan-conflict__choice" data-scan-conflict="queue">
                    Queue this scan
                </button>
                <p class="od-scan-conflict__hint">Default — starts after the current job finishes (safer for Unraid/NAS load).</p>
                <button type="button" class="btn btn-outline-warning od-scan-conflict__choice" data-scan-conflict="force">
                    Force run now (parallel)
                </button>
                <p class="od-scan-conflict__warn" role="note">
                    May spike CPU and disk I/O on Unraid/NAS while two scans share the same storage.
                    Prefer Queue unless you know the host can take the load.
                </p>
            </div>
            <div class="od-scan-conflict__actions">
                <button type="button" class="btn btn-secondary" data-scan-conflict="cancel">Cancel</button>
            </div>
        </div>
    `;
    document.body.appendChild(root);
    return root;
}

/**
 * @param {(policy: 'queue'|'force') => void} onChoose
 * @param {() => void} [onCancel]
 */
function openScanConflictModal(onChoose, onCancel) {
    const root = ensureScanConflictModal();
    root.hidden = false;
    const queueBtn = root.querySelector('[data-scan-conflict="queue"]');
    if (queueBtn) queueBtn.focus();

    function cleanup() {
        root.hidden = true;
        root.removeEventListener('click', onRootClick);
        document.removeEventListener('keydown', onKey);
        root.querySelectorAll('[data-scan-conflict]').forEach((el) => {
            el.removeEventListener('click', onAction);
        });
    }

    function onAction(event) {
        const action = event.currentTarget.getAttribute('data-scan-conflict');
        if (action === 'cancel') {
            cleanup();
            if (onCancel) onCancel();
            return;
        }
        cleanup();
        onChoose(action === 'force' ? SCAN_QUEUE_POLICY.FORCE : SCAN_QUEUE_POLICY.QUEUE);
    }

    function onRootClick(event) {
        if (event.target === root) {
            cleanup();
            if (onCancel) onCancel();
        }
    }

    function onKey(event) {
        if (event.key === 'Escape') {
            cleanup();
            if (onCancel) onCancel();
        }
    }

    root.querySelectorAll('[data-scan-conflict]').forEach((el) => {
        el.addEventListener('click', onAction);
    });
    root.addEventListener('click', onRootClick);
    document.addEventListener('keydown', onKey);
}

function applyQueueFieldsToForm(form, policy) {
    const fields = buildScanQueueRequestFields(policy);
    ;['queue_policy', 'force_parallel'].forEach((name) => {
        let input = form.querySelector(`input[name="${name}"]`);
        if (!input) {
            input = document.createElement('input');
            input.type = 'hidden';
            input.name = name;
            form.appendChild(input);
        }
        input.value = name === 'force_parallel' ? (fields.force_parallel ? '1' : '0') : fields.queue_policy;
    });
}

function clearQueueFieldsFromForm(form) {
    form.querySelectorAll('input[name="queue_policy"], input[name="force_parallel"]').forEach((el) => el.remove());
}

/**
 * Preserve submit button name/value after conflict modal.
 * Bare form.requestSubmit() / form.submit() drops `submit=AutoScan|ManualScan`
 * and Flask routes the POST as "Unrecognized action".
 */
function ensureScanSubmitAction(form, submitter) {
    const fromSubmitter =
        submitter && submitter.getAttribute && submitter.getAttribute('name') === 'submit'
            ? submitter.value
            : '';
    const fromButton = form.querySelector('button[type="submit"][name="submit"]');
    const action =
        fromSubmitter
        || (fromButton && fromButton.value)
        || (form.id === 'manualScanForm' ? 'ManualScan' : 'AutoScan');
    let input = form.querySelector('input[data-od-scan-submit-action]');
    if (!input) {
        input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'submit';
        input.setAttribute('data-od-scan-submit-action', '1');
        form.appendChild(input);
    }
    input.value = action;
    return { action, submitter: submitter && form.contains(submitter) ? submitter : fromButton };
}

async function copyPathToClipboard(path) {
    try {
        if (navigator.clipboard && window.isSecureContext) {
            await navigator.clipboard.writeText(path);
        } else {
            const textarea = document.createElement('textarea');
            textarea.value = path;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.focus();
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
        }
        return true;
    } catch (error) {
        console.error('Copy to clipboard failed:', error);
        return false;
    }
}

function attachDeleteFolderFormListeners() {
    document.querySelectorAll('.delete-folder-form').forEach(form => {
        if (!form.dataset.listenerAdded) {
            form.addEventListener('submit', function(event) {
                event.preventDefault();
                const folderPath = form.querySelector('[name="folder_path"]').value;
                
                // Add confirmation dialog
                if (!confirm(`Are you sure you want to delete the folder ${folderPath} FROM DISK?`)) {
                    console.log("Deletion cancelled by user");
                    return; // Exit the function if user cancels
                }

                showSpinner();
                const csrfToken = CSRFUtils.getToken();

                console.log("Attempting to delete folder with path:", folderPath);

                fetch('/delete_folder', {
                    method: 'POST',
                    headers: CSRFUtils.getHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({folder_path: folderPath})
                })
                .then(response => response.json())
                .then(data => {
                    console.log("Server response:", data);

                    if(data.status === 'success') {
                        console.log("Deletion successful, removing row.");
                        form.closest('tr').remove();
                    } else {
                        console.log("Deletion not successful:", data.message);
                        if (data.message === "The specified path does not exist or is not a folder. Entry removed if it was in the database.") {
                            console.log("Folder does not exist, removing row.");
                            form.closest('tr').remove();
                        }
                    }
                    alert(data.message);
                })
                .catch(error => {
                    console.error('Fetch error:', error);
                })
                .finally(() => {
                    hideSpinner();
                });
            });
            form.dataset.listenerAdded = 'true';
        }
    });
}

/** activeTab token (URL / localStorage / meta) → the pane it names. */
const SCAN_TAB_PANES = {
    libraries: '#librariesPanel',
    library: '#librariesPanel',
    deleteLibrary: '#librariesPanel',
    auto: '#autoScan',
    jobs: '#scanJobs',
    tools: '#libraryTools',
    manual: '#manualScan',
    unmatched: '#unmatchedFolders',
    scan_filters: '#scanFilters',
    file_extensions: '#fileExtensions',
    image_queue: '#imageQueue',
};

/** The reverse map, for writing the active pane back to the URL. */
const SCAN_PANE_TABS = {
    librariesPanel: 'libraries',
    autoScan: 'auto',
    scanJobs: 'jobs',
    libraryTools: 'tools',
    manualScan: 'manual',
    unmatchedFolders: 'unmatched',
    scanFilters: 'scan_filters',
    fileExtensions: 'file_extensions',
    imageQueue: 'image_queue',
};

/**
 * Every tab trigger on this page, whichever chrome drew it.
 *
 * Selected by what it *targets*, never by its own id: bar two
 * (`enable_new_chrome`, on by default) replaced the Bootstrap strip with
 * `.od-seg__item` anchors that carry the same `data-bs-toggle="tab"` and
 * `href="#autoScan"` but none of the old `#autoScan-tab` ids. The template's
 * image-queue hook already selects this way for the same reason.
 */
function scanTabTriggers() {
    return document.querySelectorAll('[data-bs-toggle="tab"][href^="#"]');
}

function isScanPaneActive(paneId) {
    const pane = document.getElementById(paneId);
    return Boolean(pane && pane.classList.contains('active'));
}

/** Auto pane or the Scan → Jobs view — the only surfaces that show the jobs table. */
function isScanJobsSurfaceVisible() {
    return isScanPaneActive('autoScan')
        || isScanPaneActive('scanJobs');
}

/** API may send last_run as "Not Available" when unset — only real parseable stamps count. */
function isRealJobTimestamp(value) {
    if (value == null || value === '') return false;
    const text = String(value).trim();
    if (!text || text === 'Not Available' || text === 'Not Scheduled') return false;
    return !Number.isNaN(Date.parse(text));
}

/** Prefer last_run, else started_at; short local YYYY-MM-DD HH:MM for the When column. */
function formatJobWhen(job) {
    const raw = isRealJobTimestamp(job && job.last_run)
        ? job.last_run
        : (isRealJobTimestamp(job && job.started_at) ? job.started_at : null);
    if (!raw) return { display: '—', sort: '' };
    const parsed = Date.parse(raw);
    if (Number.isNaN(parsed)) return { display: '—', sort: '' };
    const d = new Date(parsed);
    const pad = (n) => String(n).padStart(2, '0');
    const display = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    return { display, sort: d.toISOString() };
}

function csvEscapeCell(value) {
    const text = String(value == null ? '' : value);
    if (/[",\n\r]/.test(text)) {
        return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
}

function downloadScanJobsCsv(jobs) {
    const rows = Array.isArray(jobs) ? jobs : [];
    const header = ['id', 'when', 'library', 'path', 'status', 'progress', 'error'];
    const lines = [header.join(',')];
    rows.forEach((job) => {
        const { display: when } = formatJobWhen(job);
        const { processed, total } = (() => {
            const success = Number(job.folders_success) || 0;
            const failed = Number(job.folders_failed) || 0;
            const tot = Number(job.total_folders) || 0;
            return { processed: success + failed, total: tot };
        })();
        const progress = total ? `${processed}/${total}` : '';
        lines.push([
            csvEscapeCell(job.id || ''),
            csvEscapeCell(when),
            csvEscapeCell(job.library_name || ''),
            csvEscapeCell(job.scan_folder || ''),
            csvEscapeCell(job.status || ''),
            csvEscapeCell(progress),
            csvEscapeCell(job.error_message || ''),
        ].join(','));
    });
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `scan-jobs-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
}

function syncAutoScheduleRows() {
    const kind = document.getElementById('autoScheduleKind');
    const intervalRow = document.getElementById('autoScheduleIntervalRow');
    const cronRow = document.getElementById('autoScheduleCronRow');
    if (!kind) return;
    const value = kind.value;
    if (intervalRow) intervalRow.hidden = value !== 'interval';
    if (cronRow) cronRow.hidden = value !== 'cron';
}

/**
 * Show one tab pane, with or without a trigger to drive it.
 *
 * This used to be a bare `new bootstrap.Tab(document.querySelector('#…-tab'))`.
 * Under bar two that selector is null, Bootstrap dereferences it, and the
 * TypeError aborted the rest of this DOMContentLoaded handler — so every
 * binding registered after it was silently lost, the Browse button (which
 * binds ~70 lines further down) included. Missing trigger is now a normal
 * case: fall back to driving the pane classes directly.
 */
function showScanTab(paneSelector) {
    const trigger = document.querySelector(
        '[data-bs-toggle="tab"][href="' + paneSelector + '"]'
    );
    if (trigger && window.bootstrap && window.bootstrap.Tab) {
        new bootstrap.Tab(trigger).show();
        return;
    }
    const pane = document.querySelector(paneSelector);
    if (!pane || !pane.parentElement) return;
    pane.parentElement
        .querySelectorAll(':scope > .tab-pane')
        .forEach(function (el) {
            el.classList.remove('active', 'show');
        });
    // `show` matters for the panes the server rendered with `fade`.
    pane.classList.add('active', 'show');
}

document.addEventListener('DOMContentLoaded', function() {
    console.log("Document loaded. Setting up form submission handlers and tab activation based on activeTab.");

    // Initialize tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-toggle="tooltip"]'))
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    })

    // Simple table references - no DataTables initialization needed
    const scanJobsTableBody = document.getElementById('jobsTableBody');
    const unmatchedTableBody = document.getElementById('unmatchedFoldersTableBody');
    let scanJobsPollInFlight = false;
    let unmatchedPollInFlight = false;
    // Assigned below; tab `shown` can fire before those assignments during
    // the same DOMContentLoaded turn, so the listeners must always see a function.
    let updateScanJobs = () => Promise.resolve();
    let updateUnmatchedFolders = () => Promise.resolve();
    let badMatchReasons = [];

    const urlParams = new URLSearchParams(window.location.search);
    const urlActiveTab = urlParams.get('active_tab');
    const metaActiveTab = document.querySelector('meta[name="active-tab"]').getAttribute('content');
    const storedActiveTab = localStorage.getItem('scan_management_active_tab');

    // Priority: URL parameter > localStorage > meta tag > default 'auto'
    const activeTab = urlActiveTab || storedActiveTab || metaActiveTab || 'auto';
    console.log("Active tab determined:", activeTab, {urlActiveTab, storedActiveTab, metaActiveTab});

    // The libraries pane is not rendered for every operator, so fall back to
    // Auto Scan the way the old id-based branch did.
    const requestedPane = SCAN_TAB_PANES[activeTab] || '#autoScan';
    const targetPane =
        document.querySelector(requestedPane) ? requestedPane : '#autoScan';
    console.log("Activating tab pane:", targetPane);
    showScanTab(targetPane);

    // Add event listeners to all tab links to update URL and localStorage when clicked
    scanTabTriggers().forEach(tab => {
        tab.addEventListener('shown.bs.tab', function(event) {
            const tabId = event.target.getAttribute('href').substring(1); // Remove # from href
            const activeTabValue = SCAN_PANE_TABS[tabId] || 'auto';

            // Store in localStorage for persistence
            localStorage.setItem('scan_management_active_tab', activeTabValue);

            // Update URL without page reload
            const url = new URL(window.location.href);
            url.searchParams.set('active_tab', activeTabValue);
            window.history.replaceState({}, '', url.toString());

            if (activeTabValue === 'unmatched') {
                updateUnmatchedFolders();
            }
            if (activeTabValue === 'auto' || activeTabValue === 'jobs') {
                updateScanJobs();
            }
        });
    });

    // Prevent form submission on pressing Enter in path inputs; trigger Browse instead
    const autoScanForm = document.querySelector('#autoScan form');
    if (autoScanForm) {
        autoScanForm.addEventListener('keydown', function(event) {
            if (event.key === 'Enter' && event.target && event.target.tagName === 'INPUT') {
                event.preventDefault();
                const browseFoldersBtn = document.querySelector('#browseFoldersBtn');
                if (browseFoldersBtn) {
                    browseFoldersBtn.click();
                }
            }
        });
    }

    // Same for manual scan form
    const manualScanForm = document.querySelector('#manualScan form');
    if (manualScanForm) {
        manualScanForm.addEventListener('keydown', function(event) {
            if (event.key === 'Enter' && event.target && event.target.tagName === 'INPUT') {
                event.preventDefault();
                const browseFoldersBtnManual = document.querySelector('#browseFoldersBtnManual');
                if (browseFoldersBtnManual) {
                    browseFoldersBtnManual.click();
                }
            }
        });
    }

    setupFolderBrowse('#browseFoldersBtn', '#folderContents', '#loadingSpinner', '#upFolderBtn', '#folder_path', 'currentPathAuto');
    setupFolderBrowse('#browseFoldersBtnManual', '#folderContentsManual', '#loadingSpinnerManual', '#upFolderBtnManual', '#manualFolderPath', 'currentPathManual');
    loadScanLocations();

    // No complex toggle functionality needed for simplified table

    var csrfToken = CSRFUtils.getToken();

    // Helper function to get user-friendly status display
    function getDisplayStatus(job) {
        if (job.status === 'Failed' && job.error_message) {
            if (job.error_message === 'Scan cancelled by user') {
                return 'Cancelled';
            } else if (job.error_message === 'Scan job interrupted by server restart') {
                return 'Interrupted by server restart';
            }
        }
        return job.status;
    }

    // Every other reason a scan failed, which used to be invisible here.
    //
    // getDisplayStatus translates two specific messages into friendly statuses
    // and lets the rest fall through to a bare "Failed" — so a job reclaimed
    // because its owner process died reported nothing at all, and the operator
    // saw a queue that had simply stopped with no explanation. That is the
    // exact confusion the scan-ownership work set out to end, and this surface
    // was still hiding it. Any Failed job with a reason now shows the reason.
    function failureReason(job, displayStatus) {
        if (job.status !== 'Failed' || !job.error_message) return '';
        // Already said by the status word itself — do not say it twice.
        if (displayStatus !== 'Failed') return '';
        return job.error_message;
    }

    function progressCounts(job) {
        const success = Number(job.folders_success) || 0;
        const failed = Number(job.folders_failed) || 0;
        const total = Number(job.total_folders) || 0;
        const processed = success + failed;
        const percentage = total > 0
            ? (Number(job.progress_percentage) || Math.round((processed / total) * 1000) / 10)
            : 0;
        return { success, failed, total, processed, percentage };
    }

    function progressColumnHtml(job) {
        const { processed, total, percentage } = progressCounts(job);
        const timing = scanJobTimingLine(job);
        const timingHtml = timing
            ? `<div class="scan-job-timing" title="Elapsed / ETA">${escapeHtml(timing)}</div>`
            : '';
        if (job.status === 'Running' && total > 0) {
            return `
                            <div class="scan-progress">
                                <div class="progress mb-1" style="height: 20px;">
                                    <div class="progress-bar" style="width: ${percentage}%"></div>
                                </div>
                                <div class="progress-info">
                                    <span class="progress-numbers">${processed}/${total} (${percentage}%)</span>
                                </div>
                                ${timingHtml}
                                <div class="progress-status">
                                    <small class="text-bright-green">${escapeHtml(job.current_processing || 'Processing...')}</small>
                                </div>
                            </div>
                        `;
        }
        if (job.status === 'Running') {
            return `
                            <div class="scan-progress">
                                <div class="progress-status">
                                    <span class="text-bright-green">${escapeHtml(job.current_processing || 'Processing...')}</span>
                                </div>
                                ${timingHtml}
                            </div>
                        `;
        }
        if (job.status === 'Stopping') {
            return `
                            <div class="scan-progress">
                                <div class="progress-status">
                                    <span class="text-warning">
                                        <span class="od-spinner od-spinner--sm" aria-hidden="true"></span>
                                        Stopping… (${processed}/${total || '?'})
                                    </span>
                                </div>
                                ${timingHtml}
                                <div class="progress-status">
                                    <small class="text-muted">Finishing in-flight folders, then cancelling the rest</small>
                                </div>
                            </div>
                        `;
        }
        if (isScanQueuedStatus(job.status)) {
            const pos = job.queue_position != null ? ` #${job.queue_position}` : '';
            const waitNote = timing ? ` · ${escapeHtml(timing)}` : ' — waiting for active scan';
            return `<span class="text-info">⏳ Queued${pos}${waitNote}</span>`;
        }
        if (job.status === 'Completed' || job.status === 'Scheduled') {
            return `<span class="text-success">✓ ${processed}/${total || processed}</span>`;
        }
        if (job.status === 'Cancelled') {
            return `<span class="text-warning">⏹ Stopped ${processed}/${total || processed}</span>`;
        }
        if (job.status === 'Failed') {
            const cancelledMsg = job.error_message === 'Scan cancelled by user';
            return cancelledMsg
                ? `<span class="text-warning">⏹ Stopped ${processed}/${total || processed}</span>`
                : `<span class="text-danger">✗ ${processed}/${total || processed}</span>`;
        }
        return total ? `${processed}/${total}` : '—';
    }

    function patchScanJobProgressRows(jobs) {
        if (!scanJobsTableBody) return false;
        for (const job of jobs) {
            const row = scanJobsTableBody.querySelector(`tr[data-job-id="${job.id}"]`);
            // ID, When, Library, Path, Status, Progress, Actions → Progress is index 5
            if (!row || row.children.length < 7) return false;
            const { percentage } = progressCounts(job);
            const when = formatJobWhen(job);
            row.setAttribute('data-sort-progress', String(percentage));
            row.setAttribute('data-sort-when', when.sort);
            row.children[1].textContent = when.display;
            row.children[5].innerHTML = progressColumnHtml(job);
        }
        return true;
    }

    // Tracks whether any job is Running/Stopping — used by Start Scan conflict modal.
    let scanBusy = false;
    let scanJobFilters = loadScanJobFilters();

    function populateScanJobLibraryFilter() {
        const select = document.getElementById('scanJobsLibraryFilter');
        if (!select) return;
        const source = document.getElementById('libraryUuid');
        const previous = scanJobFilters.library_uuid || select.value || '';
        const options = ['<option value="">All libraries</option>'];
        if (source) {
            Array.from(source.options).forEach((opt) => {
                if (!opt.value) return;
                options.push(
                    `<option value="${escapeHtml(opt.value)}">${escapeHtml(opt.textContent || opt.value)}</option>`
                );
            });
        }
        select.innerHTML = options.join('');
        select.value = previous;
        scanJobFilters.library_uuid = select.value || '';
    }

    function syncScanJobFilterControls() {
        const root = document.getElementById('scanJobsFilters');
        if (!root) return;
        root.querySelectorAll('[data-scan-status]').forEach((chip) => {
            const status = chip.getAttribute('data-scan-status');
            const active = !scanJobFilters.statuses.length
                ? status === 'All'
                : status !== 'All' && scanJobFilters.statuses.includes(status);
            chip.classList.toggle('is-active', active);
            chip.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        const librarySelect = document.getElementById('scanJobsLibraryFilter');
        if (librarySelect) librarySelect.value = scanJobFilters.library_uuid || '';
        const pathInput = document.getElementById('scanJobsPathFilter');
        if (pathInput && pathInput.value !== (scanJobFilters.q || '')) {
            pathInput.value = scanJobFilters.q || '';
        }
    }

    function applyScanJobFilters(next) {
        scanJobFilters = {
            statuses: Array.isArray(next.statuses) ? next.statuses.slice() : [],
            library_uuid: String(next.library_uuid || ''),
            q: String(next.q || ''),
        };
        saveScanJobFilters(scanJobFilters);
        syncScanJobFilterControls();
        updateScanJobs();
    }

    function bindScanJobFilters() {
        const root = document.getElementById('scanJobsFilters');
        if (!root || root.dataset.bound === '1') return;
        root.dataset.bound = '1';
        populateScanJobLibraryFilter();
        syncScanJobFilterControls();

        root.querySelectorAll('[data-scan-status]').forEach((chip) => {
            chip.addEventListener('click', () => {
                const status = chip.getAttribute('data-scan-status');
                if (status === 'All') {
                    applyScanJobFilters({ ...scanJobFilters, statuses: [] });
                    return;
                }
                const set = new Set(scanJobFilters.statuses);
                if (set.has(status)) set.delete(status);
                else set.add(status);
                applyScanJobFilters({ ...scanJobFilters, statuses: Array.from(set) });
            });
        });

        const librarySelect = document.getElementById('scanJobsLibraryFilter');
        if (librarySelect) {
            librarySelect.addEventListener('change', () => {
                applyScanJobFilters({ ...scanJobFilters, library_uuid: librarySelect.value || '' });
            });
        }

        const pathInput = document.getElementById('scanJobsPathFilter');
        if (pathInput) {
            let debounce = null;
            pathInput.addEventListener('input', () => {
                clearTimeout(debounce);
                debounce = setTimeout(() => {
                    applyScanJobFilters({ ...scanJobFilters, q: pathInput.value || '' });
                }, 250);
            });
        }

        const libraryUuid = document.getElementById('libraryUuid');
        if (libraryUuid) {
            libraryUuid.addEventListener('change', () => populateScanJobLibraryFilter());
        }
    }

    // Skip wiping the jobs table when only progress ticks. A full innerHTML
    // rebuild every 3s was freezing Libraries & scans (buttons and tab
    // switches stopped responding while the main thread rebuilt rows).
    let lastScanJobsStructureSignature = '';
    let lastScanJobsProgressSignature = '';

    updateScanJobs = () => {
        if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
            return Promise.resolve();
        }
        if (scanJobsPollInFlight) {
            return Promise.resolve();
        }
        scanJobsPollInFlight = true;
        return fetch(buildScanJobsStatusUrl(scanJobFilters), { cache: 'no-store' })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`scan_jobs_status HTTP ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                const allJobs = Array.isArray(data) ? data.slice() : [];
                // Soft-degrade: Backend may ignore query params — always filter client-side.
                const filtered = filterScanJobsClientSide(allJobs, scanJobFilters);

                // Sort: active → queued → rest by last_run
                filtered.sort((a, b) => {
                    const aBusy = isScanBusyStatus(a.status) ? 0 : isScanQueuedStatus(a.status) ? 1 : 2;
                    const bBusy = isScanBusyStatus(b.status) ? 0 : isScanQueuedStatus(b.status) ? 1 : 2;
                    if (aBusy !== bBusy) return aBusy - bBusy;
                    return new Date(b.last_run || 0) - new Date(a.last_run || 0);
                });
                // CSV export uses the current filtered list.
                window.__odLastScanJobsPayload = filtered;

                const isAnyJobRunning = allJobs.some(j => isScanBusyStatus(j.status));
                scanBusy = isAnyJobRunning;
                // Banner uses full list so filters don't hide an active scan indicator.
                if (isScanPaneActive('autoScan')) {
                    updateAutoScanStatusIcon(allJobs);
                }

                if (!isScanJobsSurfaceVisible() || !scanJobsTableBody) {
                    // Keep last* as the last painted table so returning to Auto/Jobs
                    // can patch progress instead of wiping rows.
                    return;
                }
                const structure = scanJobsStructureSignature(filtered, { busy: isAnyJobRunning });
                const progress = scanJobsProgressSignature(filtered);
                if (structure === lastScanJobsStructureSignature && progress === lastScanJobsProgressSignature) {
                    return;
                }
                if (structure === lastScanJobsStructureSignature && patchScanJobProgressRows(filtered)) {
                    lastScanJobsProgressSignature = progress;
                    return;
                }
                lastScanJobsStructureSignature = structure;
                lastScanJobsProgressSignature = progress;

                scanJobsTableBody.innerHTML = '';

                if (!filtered.length) {
                    const empty = document.createElement('tr');
                    empty.className = 'jobs-empty-row';
                    const hasFilters = (scanJobFilters.statuses && scanJobFilters.statuses.length)
                        || scanJobFilters.library_uuid
                        || (scanJobFilters.q && scanJobFilters.q.trim());
                    empty.innerHTML = `<td colspan="7">${hasFilters
                        ? 'No scan jobs match the current filters.'
                        : 'No scan jobs yet. Start a scan from Auto or Manual.'}</td>`;
                    scanJobsTableBody.appendChild(empty);
                    return;
                }

                filtered.forEach(job => {
                    const { percentage } = progressCounts(job);
                    const progressColumn = progressColumnHtml(job);

                    let actionsColumn = '—';
                    if (job.status === 'Running') {
                        actionsColumn = `<form action="/cancel_scan_job/${job.id}" method="post" style="display: inline-block;">
                                <input type="hidden" name="csrf_token" value="${csrfToken}">
                                <button type="submit" class="btn btn-warning btn-sm" title="Cancel Scan">Stop</button>
                            </form>`;
                    } else if (job.status === 'Stopping') {
                        actionsColumn = `<button class="btn btn-warning btn-sm" disabled title="Scan is stopping, please wait...">
                                <span class="od-spinner od-spinner--sm" aria-hidden="true"></span>
                                Stopping…
                            </button>`;
                    } else if (isScanQueuedStatus(job.status)) {
                        actionsColumn = `<form action="/cancel_scan_job/${job.id}" method="post" style="display: inline-block;">
                                <input type="hidden" name="csrf_token" value="${csrfToken}">
                                <button type="submit" class="btn btn-outline-warning btn-sm" title="Cancel queued scan before it starts">Cancel queue</button>
                            </form>`;
                    } else if (isAnyJobRunning) {
                        actionsColumn = `<button type="button" class="btn btn-info btn-sm od-scan-restart-busy"
                                data-restart-url="/restart_scan_job/${job.id}"
                                title="Another scan is running — queue or force restart">↻</button>`;
                    } else {
                        actionsColumn = `<form action="/restart_scan_job/${job.id}" method="post" style="display: inline-block;">
                                    <input type="hidden" name="csrf_token" value="${csrfToken}">
                                    <button type="submit" class="btn btn-info btn-sm" title="Restart Scan">↻</button>
                                </form>`;
                    }

                    // Status plus, when there is one, the reason underneath it.
                    const displayStatus = getDisplayStatus(job);
                    const reason = failureReason(job, displayStatus);
                    const statusCell = reason
                        ? `${escapeHtml(displayStatus)}<div class="od-scan-fail-reason">${escapeHtml(reason)}</div>`
                        : escapeHtml(displayStatus);

                    const row = document.createElement('tr');
                    // Sort key for the Progress column (W27-C2). The cell renders a bar
                    // and a "3/25 (12%)" caption, neither of which compares numerically
                    // as text — od_sortable_table.js reads this instead.
                    const { display: whenDisplay, sort: whenSort } = formatJobWhen(job);
                    row.setAttribute('data-job-id', job.id);
                    row.setAttribute('data-sort-progress', String(percentage));
                    row.setAttribute('data-sort-when', whenSort);
                    row.innerHTML = `
                        <td>${job.id.substring(0, 8)}</td>
                        <td>${escapeHtml(whenDisplay)}</td>
                        <td>${escapeHtml(job.library_name || 'N/A')}</td>
                        <td>${escapeHtml(job.scan_folder || 'N/A')}</td>
                        <td>${statusCell}</td>
                        <td>${progressColumn}</td>
                        <td>${actionsColumn}</td>
                    `;
                    scanJobsTableBody.appendChild(row);
                });

                scanJobsTableBody.querySelectorAll('.od-scan-restart-busy').forEach((btn) => {
                    btn.addEventListener('click', () => {
                        const url = btn.getAttribute('data-restart-url');
                        openScanConflictModal((policy) => {
                            const form = document.createElement('form');
                            form.method = 'post';
                            form.action = url;
                            const csrf = document.createElement('input');
                            csrf.type = 'hidden';
                            csrf.name = 'csrf_token';
                            csrf.value = csrfToken;
                            form.appendChild(csrf);
                            applyQueueFieldsToForm(form, policy);
                            document.body.appendChild(form);
                            form.submit();
                        });
                    });
                });
            })
            .catch(error => console.error('Error fetching scan jobs status:', error))
            .finally(() => {
                scanJobsPollInFlight = false;
                armScanJobsPoll();
            });
    };

    bindScanJobFilters();

    // Schedule kind toggles interval/cron rows on Auto.
    syncAutoScheduleRows();
    const autoScheduleKind = document.getElementById('autoScheduleKind');
    if (autoScheduleKind) {
        autoScheduleKind.addEventListener('change', syncAutoScheduleRows);
    }

    // Export CSV — button may appear on jobs page and/or modal toolbar.
    document.querySelectorAll('[data-scan-jobs-export]').forEach((btn) => {
        btn.addEventListener('click', () => {
            downloadScanJobsCsv(window.__odLastScanJobsPayload || []);
        });
    });

    function interceptScanFormSubmit(form) {
        if (!form || form.dataset.scanConflictBound) return;
        form.dataset.scanConflictBound = '1';
        form.addEventListener('submit', function(event) {
            // Allow programmatic re-submit after modal choice.
            if (form.dataset.scanConflictProceed === '1') {
                form.dataset.scanConflictProceed = '0';
                return;
            }
            if (!scanBusy) {
                clearQueueFieldsFromForm(form);
                return;
            }
            event.preventDefault();
            const submitter = event.submitter || null;
            openScanConflictModal((policy) => {
                applyQueueFieldsToForm(form, policy);
                const ensured = ensureScanSubmitAction(form, submitter);
                form.dataset.scanConflictProceed = '1';
                if (typeof form.requestSubmit === 'function') {
                    if (ensured.submitter) {
                        form.requestSubmit(ensured.submitter);
                    } else {
                        form.requestSubmit();
                    }
                } else {
                    HTMLFormElement.prototype.submit.call(form);
                }
            });
        });
    }

    interceptScanFormSubmit(autoScanForm);
    // Manual busy → same Queue/Force conflict UX as Auto (queue_policy / force_parallel).
    // Idle Manual stays List Games identify — intercept clears queue fields when !scanBusy.
    interceptScanFormSubmit(manualScanForm);

    // Wave 17 selection + soft filter state (client interim; prefer server q= when present)
    const unmatchedSelectedIds = new Set();
    let currentWhyFilter = 'all';
    let currentKindFilter = 'all';
    let currentLeafFilter = 'all';
    let currentTriageFilter = 'all';
    let unmatchedNameEndpointReady = null; // null=unknown, true/false after probe
    let unmatchedLibraryFilter = '';
    let unmatchedPlatformFilter = '';
    let unmatchedRegionFilter = '';
    let unmatchedPageLimit = 150;
    let unmatchedPageOffset = 0;
    let unmatchedTotalCount = 0;

    function syncUnmatchedExportLinks() {
        const params = new URLSearchParams();
        if (currentSearch) params.set('q', currentSearch);
        if (currentFilter !== 'all') params.set('status', currentFilter);
        if (unmatchedLibraryFilter) params.set('library_uuid', unmatchedLibraryFilter);
        if (unmatchedPlatformFilter) params.set('platform', unmatchedPlatformFilter);
        if (unmatchedRegionFilter) params.set('rom_region', unmatchedRegionFilter);
        if (currentWhyFilter !== 'all') params.set('why', currentWhyFilter);
        if (currentKindFilter !== 'all') {
            params.set('suggested_kind', currentKindFilter === 'none' ? '' : currentKindFilter);
        }
        const qs = params.toString();
        ['exportUnmatchedCsvBtn', 'exportUnmatchedJsonBtn'].forEach((id) => {
            const link = document.getElementById(id);
            if (!link) return;
            const url = new URL(link.href, window.location.origin);
            // Keep format from existing href
            const format = url.searchParams.get('format') || (id.includes('Json') ? 'json' : 'csv');
            const next = new URL('/api/unmatched_folders/export', window.location.origin);
            params.forEach((value, key) => next.searchParams.set(key, value));
            next.searchParams.set('format', format);
            if (!next.searchParams.get('status')) next.searchParams.set('status', 'all');
            link.href = next.pathname + '?' + next.searchParams.toString();
        });
    }

    function fetchUnmatchedList() {
        const params = new URLSearchParams();
        if (currentSearch) params.set('q', currentSearch);
        if (currentFilter !== 'all') params.set('status', currentFilter);
        if (currentWhyFilter !== 'all') {
            params.set('why', currentWhyFilter);
            params.set('match_reason', currentWhyFilter);
        }
        if (currentKindFilter !== 'all') {
            params.set('suggested_kind', currentKindFilter === 'none' ? '' : currentKindFilter);
        }
        if (unmatchedLibraryFilter) params.set('library_uuid', unmatchedLibraryFilter);
        if (unmatchedPlatformFilter) params.set('platform', unmatchedPlatformFilter);
        if (unmatchedRegionFilter) params.set('rom_region', unmatchedRegionFilter);
        params.set('limit', String(unmatchedPageLimit));
        params.set('offset', String(unmatchedPageOffset));
        params.set('paginate', '1');
        const qs = params.toString();
        const url = qs ? `/api/unmatched_folders?${qs}` : '/api/unmatched_folders';
        syncUnmatchedExportLinks();
        return fetch(url, { cache: 'no-store' })
            .then((response) => {
                if (!response.ok) throw new Error(`unmatched_folders ${response.status}`);
                return response.json();
            })
            .then((data) => {
                if (Array.isArray(data)) {
                    unmatchedTotalCount = data.length;
                    return data;
                }
                unmatchedTotalCount = Number(data.total || data.count || 0) || 0;
                return Array.isArray(data.items) ? data.items : [];
            });
    }

    /** Soft-enrich Duplicate rows with matched_game from /duplicates when list omits it. */
    function enrichUnmatchedWithDuplicates(folders) {
        const needs = folders.filter((f) => {
            if (!(f.status === 'Duplicate' || f.matched_game_uuid || f.duplicate_of || f.matched_game)) {
                return false;
            }
            return !normalizeMatchedGame(f);
        });
        if (!needs.length) return Promise.resolve(folders);
        return fetch('/api/unmatched_folders/duplicates', { cache: 'no-store' })
            .then((response) => (response.ok ? response.json() : { duplicates: [] }))
            .then((payload) => {
                const byId = new Map();
                (payload.duplicates || []).forEach((dup) => {
                    const cand = (dup.candidates && dup.candidates[0]) || null;
                    if (!cand) return;
                    byId.set(String(dup.id), {
                        uuid: cand.uuid,
                        name: cand.name,
                        path: cand.path,
                        cover_url: cand.cover_url,
                        match_score: cand.match_score != null ? cand.match_score : dup.match_score,
                        match_reason: cand.match_reason || dup.match_reason,
                        transforms: Array.isArray(dup.transforms) ? dup.transforms : null,
                    });
                });
                return folders.map((folder) => {
                    const hit = byId.get(String(folder.id));
                    const folderHasTrail = Array.isArray(folder.transforms) && folder.transforms.length > 0;
                    const softTransforms =
                        !folderHasTrail && hit && Array.isArray(hit.transforms) && hit.transforms.length
                            ? hit.transforms
                            : null;
                    if (normalizeMatchedGame(folder)) {
                        if (!softTransforms) return folder;
                        return Object.assign({}, folder, { transforms: softTransforms });
                    }
                    if (!hit) return folder;
                    const next = {
                        matched_game: hit,
                        match_score: folder.match_score != null ? folder.match_score : hit.match_score,
                        match_reason: folder.match_reason || hit.match_reason,
                    };
                    if (softTransforms) next.transforms = softTransforms;
                    return Object.assign({}, folder, next);
                });
            })
            .catch(() => folders);
    }

    let lastUnmatchedSignature = '';

    updateUnmatchedFolders = () => {
        if (!isScanPaneActive('unmatchedFolders')) {
            return Promise.resolve();
        }
        if (unmatchedPollInFlight) {
            return Promise.resolve();
        }
        unmatchedPollInFlight = true;
        const quiet = unmatchedTableBody && unmatchedTableBody.children.length > 0;
        if (!quiet) {
            showSpinner();
        }
        const priorSelected = new Set(unmatchedSelectedIds);
        // Reasons are fetched once and then cached, so the picker is populated
        // before the first row is built rather than appearing on a later redraw.
        const reasonsReady = badMatchReasons.length
            ? Promise.resolve()
            : loadBadMatchReasons();
        return reasonsReady
            .then(() => fetchUnmatchedList())
            .then((data) => enrichUnmatchedWithDuplicates(data))
            .then((data) => {
                const signature = unmatchedFoldersSignature(data);
                if (
                    signature === lastUnmatchedSignature
                    && unmatchedTableBody
                    && unmatchedTableBody.querySelector('tr[data-folder-id]')
                ) {
                    return;
                }
                if (
                    unmatchedTableBody
                    && unmatchedTableBody.contains(document.activeElement)
                ) {
                    return;
                }
                lastUnmatchedSignature = signature;

                unmatchedTableBody.innerHTML = '';
                unmatchedSelectedIds.clear();

                data.forEach((folder) => {
                    const escapedPath = escapeHtml(folder.folder_path);
                    const diskBasename = unmatchedFolderBasename(folder.folder_path);
                    const searchName = resolveUnmatchedSearchName(folder);
                    const escapedSearchName = escapeHtml(searchName);
                    const escapedDisk = escapeHtml(diskBasename);
                    const ignoreLabel = folder.status === 'Ignore' ? 'Unignore' : 'Ignore';
                    const canMarkKind = folder.status === 'Unmatched'
                        || folder.status === 'Pending'
                        || folder.status === 'Duplicate';
                    const isDuplicate = folder.status === 'Duplicate';
                    const suggestedRaw = folder.suggested_kind == null ? '' : String(folder.suggested_kind).trim().toLowerCase();
                    const suggestedKind = ['experience', 'emulator', 'tool'].includes(suggestedRaw)
                        ? suggestedRaw
                        : '';
                    const suggestedLabel = suggestedKind === 'experience'
                        ? 'Soft title'
                        : suggestedKind === 'emulator'
                            ? 'Emulator'
                            : suggestedKind === 'tool'
                                ? 'Utility'
                                : '';
                    const markKindOrder = suggestedKind
                        ? [suggestedKind, ...['experience', 'emulator', 'tool'].filter((k) => k !== suggestedKind)]
                        : ['experience', 'emulator', 'tool'];
                    const markKindButtons = canMarkKind ? markKindOrder.map((itemKind) => {
                        const label = itemKind === 'experience'
                            ? 'Soft'
                            : itemKind === 'emulator'
                                ? 'Emu'
                                : 'Util';
                        const fullLabel = itemKind === 'experience'
                            ? 'Soft title'
                            : itemKind === 'emulator'
                                ? 'Emulator'
                                : 'Utility';
                        const isSuggested = suggestedKind === itemKind;
                        const btnClass = isSuggested
                            ? 'od-cbtn mark-kind-btn is-suggested'
                            : 'od-cbtn mark-kind-btn';
                        const title = isSuggested
                            ? `Suggested: catalog as ${fullLabel} without an IGDB game match`
                            : `Catalog as ${fullLabel} without an IGDB game match`;
                        return `<button type="button" class="${btnClass}" data-folder-id="${escapeHtml(String(folder.id))}" data-item-kind="${itemKind}" data-name="${escapedSearchName}" title="${escapeHtml(title)}">Mark ${label}</button>`;
                    }).join('\n') : '';
                    const suggestedChip = suggestedKind
                        ? `<span class="unmatched-suggested-kind" title="Suggested kind from scan proposal (software path)">Suggested ${escapeHtml(suggestedLabel)}</span>`
                        : '';
                    const whyLine = formatWhyUnmatched(folder);
                    const matchScore = formatMatchScore(folder.match_score);
                    const transformTrailHtml = buildTransformTrailHtml(folder);
                    const stageEHtml = buildStageEHtml(folder);
                    const showWhyLabel = folder.status === 'Unmatched' || folder.status === 'Pending';
                    const scoreHtml = matchScore && !isDuplicate
                        ? `<span class="unmatched-why__score" title="Match confidence score">${escapeHtml(matchScore)}</span>`
                        : '';
                    const reasonLineHtml = (whyLine || (matchScore && !isDuplicate) || (showWhyLabel && (transformTrailHtml || stageEHtml)))
                        ? `<p class="unmatched-why__line"${showWhyLabel ? '' : ' data-why-kind="status"'}>${
                            showWhyLabel
                                ? '<span class="unmatched-why__label">Why unmatched?</span> '
                                : ''
                          }${scoreHtml}${scoreHtml && whyLine ? ' ' : ''}${whyLine ? escapeHtml(whyLine) : ''}</p>`
                        : '';
                    const whyHtml = (reasonLineHtml || transformTrailHtml || stageEHtml)
                        ? `<div class="unmatched-why">${reasonLineHtml}${transformTrailHtml}${stageEHtml}</div>`
                        : '';
                    const dupeOfHtml = (isDuplicate || normalizeMatchedGame(folder))
                        ? buildDupeOfHtml(folder)
                        : '';
                    const dupeFixButtons = isDuplicate
                        ? `
                        <button type="button" class="od-cbtn unmatched-fix-btn" data-folder-id="${escapeHtml(String(folder.id))}" data-fix-action="merge" title="Keep library game; clear this duplicate row">Merge</button>
                        <button type="button" class="od-cbtn unmatched-fix-btn" data-folder-id="${escapeHtml(String(folder.id))}" data-fix-action="keep" title="Reclassify as Unmatched for further review">Keep</button>
                        <button type="button" class="od-cbtn unmatched-fix-btn" data-folder-id="${escapeHtml(String(folder.id))}" data-fix-action="ignore" title="Ignore this duplicate folder">Ignore</button>`
                        : '';
                    const scanCorrectionButton = folder.status === 'Unmatched'
                        ? (folder.is_bare_update_package
                            ? `<button type="button" class="od-cbtn unmatched-place-update-btn" data-folder-id="${escapeHtml(String(folder.id))}" data-game-root-name="${escapeHtml(folder.suggested_search_name || '')}" title="Move this update under its game folder">Place update</button>`
                            : `<button type="button" class="od-cbtn unmatched-retry-match-btn" data-folder-id="${escapeHtml(String(folder.id))}" title="Retry matching with current metadata providers">Retry match</button>`)
                        : '';
                    const actionsBar = `
                        <details class="unmatched-row-menu">
                          <summary class="od-cbtn unmatched-row-menu__summary">Actions</summary>
                          <div class="unmatched-row-actions od-menu-surface" role="toolbar" aria-label="Actions for ${escapedDisk}">
                        <button type="button" class="od-cbtn reveal-path-btn" data-path="${escapedPath}" title="Open path (companion / copy) — disk tidy this wave; no disk rename">Open path</button>
                        <form action="/add_game_manual" method="GET" class="unmatched-identify-form" style="display: inline;">
                            <input type="hidden" name="full_disk_path" value="${escapedPath}">
                            <input type="hidden" name="library_uuid" value="${escapeHtml(folder.library_uuid || '')}">
                            <input type="hidden" name="platform_name" value="${escapeHtml(folder.platform_name || '')}">
                            <input type="hidden" name="platform_id" value="${escapeHtml(folder.platform_id || '')}">
                            <input type="hidden" name="from_unmatched" value="true">
                            <button type="submit" class="od-cbtn" title="Identify as game — Fix search uses Search name when set">Fix search</button>
                        </form>
                        ${markKindButtons}
                        ${scanCorrectionButton}
                        ${dupeFixButtons}
                        ${badMatchControl(folder)}
                        ${!isDuplicate ? `<button
                            type="button"
                            data-od-click="toggleIgnoreStatus"
                            data-od-arg="${folder.id}"
                            class="od-cbtn"
                            title="Ignored folders are not scanned">
                            ${ignoreLabel}
                        </button>` : ''}
                        <button type="button" data-od-click="clearEntry" data-od-arg="${folder.id}" class="od-cbtn" title="Remove from unmatched list">Clear</button>
                        <form class="delete-folder-form" style="display: inline;">
                            <input type="hidden" name="csrf_token" value="${csrfToken}">
                            <input type="hidden" name="folder_path" value="${escapedPath}">
                            <button type="submit" class="od-cbtn od-cbtn--danger" title="Delete the folder from disk">Delete</button>
                        </form>
                          </div>
                        </details>
                    `;

                    const matchReasonAttr = String(folder.match_reason || '').trim().toLowerCase();
                    const kindAttr = suggestedKind || 'none';
                    const leafType = detectLeafType(folder.folder_path);
                    const platformMismatch = detectPlatformMismatch(
                        folder.folder_path,
                        folder.library_name,
                        folder.platform_name,
                    );
                    const garbage = isGarbageScaffolding(folder);
                    const leafBadgeClass = leafType === 'file-leaf'
                        ? 'unmatched-leaf-badge'
                        : 'unmatched-leaf-badge unmatched-leaf-badge--folder';
                    const leafBadgeLabel = leafType === 'file-leaf' ? 'ROM files' : 'Folder';
                    const regionLabel = folder.rom_region ? String(folder.rom_region) : '—';
                    const triageBadgesHtml = `
                        <div class="unmatched-triage-badges">
                          <span class="${leafBadgeClass}" title="${leafType === 'file-leaf' ? 'ROM or archive files in this library' : 'Each game is its own named folder'}">${leafBadgeLabel}</span>
                          ${platformMismatch ? `<span class="unmatched-platform-mismatch" title="${escapeHtml(formatPlatformMismatchTitle(platformMismatch))}">Platform mismatch</span>` : ''}
                          ${garbage ? '<span class="unmatched-garbage-badge" title="Likely installer, redistributable, or temp scaffolding">Garbage</span>' : ''}
                        </div>`;
                    const dupeHit = normalizeMatchedGame(folder);
                    const searchBlob = [
                        folder.folder_path,
                        diskBasename,
                        searchName,
                        folder.library_name,
                        folder.platform_name,
                        folder.rom_region,
                        folder.why_unmatched,
                        folder.unmatched_reason,
                        dupeHit && dupeHit.name,
                        dupeHit && dupeHit.path,
                    ].filter(Boolean).join(' ').toLowerCase();

                    const row = document.createElement('tr');
                    row.setAttribute('data-status', folder.status);
                    row.setAttribute('data-folder-id', String(folder.id));
                    row.setAttribute('data-folder-path', String(folder.folder_path || '').toLowerCase());
                    row.setAttribute('data-library-name', String(folder.library_name || '').toLowerCase());
                    row.setAttribute('data-platform-name', String(folder.platform_name || '').toLowerCase());
                    row.setAttribute('data-sort-folder', String(searchName || diskBasename || folder.folder_path || '').toLowerCase());
                    row.setAttribute('data-sort-status', String(folder.status || '').toLowerCase());
                    row.setAttribute('data-sort-library', String(folder.library_name || '').toLowerCase());
                    row.setAttribute('data-sort-platform', String(folder.platform_name || '').toLowerCase());
                    row.setAttribute('data-sort-region', String(folder.rom_region || '').toLowerCase());
                    row.setAttribute('data-match-reason', matchReasonAttr);
                    row.setAttribute('data-suggested-kind', kindAttr);
                    row.setAttribute('data-leaf-type', leafType);
                    row.setAttribute('data-platform-mismatch', platformMismatch ? '1' : '0');
                    row.setAttribute('data-garbage', garbage ? '1' : '0');
                    row.setAttribute('data-search-blob', searchBlob);
                    row.innerHTML = `
                        <td class="col-select">
                          <input type="checkbox" class="unmatched-row-check" value="${escapeHtml(String(folder.id))}" aria-label="Select folder ${escapedDisk}">
                        </td>
                        <td class="col-path">
                          <div class="unmatched-folder-cell unmatched-folder-cell--compact">
                            <div class="unmatched-amend">
                              <label class="unmatched-amend__label" for="amend-${escapeHtml(String(folder.id))}">Search name</label>
                              <div class="unmatched-amend__row">
                                <input type="text" id="amend-${escapeHtml(String(folder.id))}" class="unmatched-amend__input" value="${escapedSearchName}" data-folder-id="${escapeHtml(String(folder.id))}" data-original="${escapedSearchName}" spellcheck="false" title="Search name for Fix search / Identify — does not rename on disk">
                                <button type="button" class="btn btn-outline-light btn-sm unmatched-amend__save" data-folder-id="${escapeHtml(String(folder.id))}" title="Save search name (does not rename on disk)">Save</button>
                              </div>
                              <div class="unmatched-amend__ondisk" title="${escapedPath}">On disk: ${escapedDisk}</div>
                            </div>
                            ${triageBadgesHtml}
                          </div>
                        </td>
                        <td class="col-status"><span class="status-${folder.status.toLowerCase()}" title="${folder.status === 'Duplicate' ? 'Same system + region already has this IGDB match with a similar title' : (folder.status === 'Unmatched' ? 'Could not auto-match to IGDB (or IGDB already used by a different-titled folder on this system)' : '')}">${folder.status === 'Duplicate' ? 'Duplicate' : folder.status}</span>${suggestedChip}${dupeOfHtml}${whyHtml}</td>
                        <td class="col-library">${escapeHtml(folder.library_name || '')}</td>
                        <td class="col-platform">${escapeHtml(folder.platform_name || '')}</td>
                        <td class="col-region">${escapeHtml(regionLabel)}</td>
                        <td class="col-actions">${actionsBar}</td>
                    `;
                    unmatchedTableBody.appendChild(row);

                    if (priorSelected.has(String(folder.id))) {
                        const check = row.querySelector('.unmatched-row-check');
                        if (check) {
                            check.checked = true;
                            unmatchedSelectedIds.add(String(folder.id));
                        }
                    }
                });
                attachDeleteFolderFormListeners();
                // No sort call: od_sortable_table.js observes this tbody and
                // re-applies the active order once these rows land.
                filterUnmatchedRows();
                updateBatchBar();
                updateSelectAllState();
            })
            .catch((error) => {
                console.error('Error fetching unmatched folders:', error);
            })
            .finally(() => {
                unmatchedPollInFlight = false;
                hideSpinner();
            });
    };

    // Copy path / reveal path — event delegation so re-rendered rows stay wired
    // --- UX-C5: "this proposed match is wrong", with a reason ----------------
    //
    // Feedback, not triage: flagging never changes the row's status and never
    // touches the library, which is what the endpoint already guarantees. The
    // vocabulary is served rather than hardcoded so it can grow without a
    // template change; if that fetch fails the picker is simply absent and the
    // rest of the table still works.

    function loadBadMatchReasons() {
        return fetch('/api/unmatched/bad_match_reasons', { credentials: 'same-origin' })
            .then((response) => (response.ok ? response.json() : null))
            .then((data) => {
                badMatchReasons = Array.isArray(data && data.reasons) ? data.reasons : [];
            })
            .catch(() => {
                badMatchReasons = [];
            });
    }

    function badMatchControl(folder) {
        if (!badMatchReasons.length) return '';
        const current = String(folder.bad_match_reason || '');
        const options = ['<option value="">Not flagged</option>']
            .concat(badMatchReasons.map((reason) => {
                const id = escapeHtml(String(reason.id));
                const selected = current === String(reason.id) ? ' selected' : '';
                return `<option value="${id}"${selected}>${escapeHtml(String(reason.label))}</option>`;
            }))
            .join('');
        const flagged = current ? ' is-flagged' : '';
        return `
            <label class="unmatched-badmatch${flagged}" title="Tell the matcher this proposal is wrong">
                <span class="unmatched-badmatch__label">Bad match</span>
                <select class="unmatched-badmatch__select" data-folder-id="${escapeHtml(String(folder.id))}" aria-label="Flag bad match for ${escapeHtml(String(folder.folder_path || folder.id))}">
                    ${options}
                </select>
            </label>
        `;
    }

    function submitBadMatch(folderId, reason, note, select) {
        if (select) select.disabled = true;
        const payload = { reason: reason || null };
        if (note) payload.note = note;
        return fetch(`/api/unmatched/${encodeURIComponent(folderId)}/bad_match`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify(payload),
        })
            .then((response) => response.json().catch(() => ({})).then((data) => {
                if (!response.ok) throw new Error(data.error || 'Could not save that.');
                return data;
            }))
            .catch((err) => {
                window.alert(err.message || 'Could not save that.');
            })
            .finally(() => {
                if (select) select.disabled = false;
            });
    }

    document.addEventListener('change', (event) => {
        const select = event.target.closest && event.target.closest('.unmatched-badmatch__select');
        if (!select) return;
        const folderId = select.getAttribute('data-folder-id');
        const reason = select.value;
        let note = null;
        if (reason === 'other') {
            // 'other' without a note is a shrug, and the API refuses it — so ask
            // here rather than posting something known to fail.
            note = window.prompt('What is wrong with this match?');
            if (note == null || !note.trim()) {
                select.value = '';
                return;
            }
            note = note.trim();
        }
        const label = select.closest('.unmatched-badmatch');
        if (label) label.classList.toggle('is-flagged', Boolean(reason));
        void submitBadMatch(folderId, reason, note, select);
    });

    // without re-escaping paths back into inline onclick strings (XSS-safe).
    function markUnmatchedKind(folderId, itemKind, name, button) {
        if (!folderId || !itemKind) return;
        if (button) {
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');
        }
        const body = { item_kind: itemKind };
        if (name) body.name = name;
        const kindLabel = itemKind === 'experience'
            ? 'Soft title'
            : itemKind === 'emulator'
                ? 'Emulator'
                : itemKind === 'tool'
                    ? 'Utility'
                    : itemKind;
        fetch(`/api/unmatched_folders/${encodeURIComponent(folderId)}/mark_kind`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify(body),
        })
            .then((response) => response.json().catch(() => ({})).then((data) => {
                if (!response.ok) {
                    throw new Error(data.error || data.message || `mark_kind ${response.status}`);
                }
                return data;
            }))
            .then((data) => {
                showToast(
                    `Cataloged “${data.name || name || 'folder'}” as ${kindLabel} (no IGDB game match)`,
                    'success',
                );
                return updateUnmatchedFolders();
            })
            .catch((err) => {
                showToast(err?.message || `Could not mark as ${kindLabel}`, 'info');
            })
            .finally(() => {
                if (button) {
                    button.disabled = false;
                    button.removeAttribute('aria-busy');
                }
            });
    }

    if (unmatchedTableBody && !unmatchedTableBody.dataset.actionsWired) {
        unmatchedTableBody.addEventListener('click', function(event) {
            const copyBtn = event.target.closest('.copy-path-btn');
            if (copyBtn) {
                const path = copyBtn.dataset.path || '';
                copyPathToClipboard(path).then(ok => {
                    showToast(ok ? 'Path copied to clipboard' : 'Could not copy path', ok ? 'success' : 'info');
                });
                return;
            }

            const popBtn = event.target.closest('.unmatched-dupe-compare__pop');
            if (popBtn) {
                const compare = popBtn.closest('.unmatched-dupe-compare');
                if (compare) showDupeComparePopout(compare);
                return;
            }

            const revealBtn = event.target.closest('.reveal-path-btn');
            if (revealBtn) {
                revealPath(revealBtn.dataset.path || '', revealBtn);
                return;
            }

            const retryMatchBtn = event.target.closest('.unmatched-retry-match-btn');
            if (retryMatchBtn) {
                retryUnmatchedMatch(retryMatchBtn.dataset.folderId || '', retryMatchBtn);
                return;
            }

            const placeUpdateBtn = event.target.closest('.unmatched-place-update-btn');
            if (placeUpdateBtn) {
                placeUnmatchedUpdate(
                    placeUpdateBtn.dataset.folderId || '',
                    placeUpdateBtn.dataset.gameRootName || '',
                    placeUpdateBtn,
                );
                return;
            }

            const markBtn = event.target.closest('.mark-kind-btn');
            if (markBtn) {
                markUnmatchedKind(
                    markBtn.dataset.folderId || '',
                    markBtn.dataset.itemKind || '',
                    markBtn.dataset.name || '',
                    markBtn,
                );
                return;
            }

            const fixBtn = event.target.closest('.unmatched-fix-btn');
            if (fixBtn) {
                fixDuplicateFolder(
                    fixBtn.dataset.folderId || '',
                    fixBtn.dataset.fixAction || '',
                    fixBtn,
                );
                return;
            }

            const amendSave = event.target.closest('.unmatched-amend__save');
            if (amendSave) {
                const folderId = amendSave.dataset.folderId || '';
                const input = unmatchedTableBody.querySelector(`.unmatched-amend__input[data-folder-id="${CSS.escape(folderId)}"]`);
                const searchName = input ? String(input.value || '').trim() : '';
                saveAmendNaming(folderId, searchName, amendSave, input);
            }
        });

        unmatchedTableBody.addEventListener('change', function(event) {
            const check = event.target.closest('.unmatched-row-check');
            if (!check) return;
            const id = String(check.value || '');
            if (!id) return;
            if (check.checked) unmatchedSelectedIds.add(id);
            else unmatchedSelectedIds.delete(id);
            updateBatchBar();
            updateSelectAllState();
        });

        unmatchedTableBody.addEventListener('keydown', function(event) {
            if (event.key !== 'Enter') return;
            const input = event.target.closest('.unmatched-amend__input');
            if (!input) return;
            event.preventDefault();
            const folderId = input.dataset.folderId || '';
            const saveBtn = unmatchedTableBody.querySelector(`.unmatched-amend__save[data-folder-id="${CSS.escape(folderId)}"]`);
            saveAmendNaming(folderId, String(input.value || '').trim(), saveBtn, input);
        });

        unmatchedTableBody.dataset.actionsWired = 'true';
    }

    function unmatchedActionRequest(folderId, action, body, button) {
        if (!folderId) return Promise.reject(new Error('Missing unmatched folder id'));
        if (button) {
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');
        }
        return fetch(`/api/unmatched_folders/${encodeURIComponent(folderId)}/${action}`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: CSRFUtils.getHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(body || {}),
        })
            .then((response) => response.json().catch(() => ({})).then((data) => {
                if (!response.ok) {
                    throw new Error(action === 'retry_match'
                        ? 'Could not retry metadata matching'
                        : 'Could not place the update folder');
                }
                return data;
            }))
            .finally(() => {
                if (button) {
                    button.disabled = false;
                    button.removeAttribute('aria-busy');
                }
            });
    }

    function retryUnmatchedMatch(folderId, button) {
        unmatchedActionRequest(folderId, 'retry_match', {}, button)
            .then((data) => {
                showToast(
                    data.matched
                        ? `Matched “${data.name || data.search_name || 'game'}” using current metadata providers`
                        : `No unique metadata match found for “${data.search_name || 'folder'}”`,
                    data.matched ? 'success' : 'info',
                );
                return updateUnmatchedFolders();
            })
            .catch((err) => showToast(err?.message || 'Could not retry matching', 'info'));
    }

    function placeUnmatchedUpdate(folderId, suggestedName, button) {
        const gameRootName = window.prompt(
            'Move this update into the game folder named:',
            suggestedName || '',
        );
        if (gameRootName == null) return;
        if (!gameRootName.trim()) {
            showToast('Enter the game folder name', 'info');
            return;
        }
        unmatchedActionRequest(folderId, 'place_update', { game_root_name: gameRootName.trim() }, button)
            .then((data) => {
                showToast(
                    data.created_game_root
                        ? `Created “${data.game_root_name}” and moved the update into it`
                        : `Moved the update into “${data.game_root_name}”`,
                    'success',
                );
                return updateUnmatchedFolders();
            })
            .catch((err) => showToast(err?.message || 'Could not place update folder', 'info'));
    }

    function fixDuplicateFolder(folderId, action, button) {
        if (!folderId || !action) return;
        if (button) {
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');
        }
        fetch(`/api/unmatched_folders/${encodeURIComponent(folderId)}/fix`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify({ action }),
        })
            .then((response) => response.json().catch(() => ({})).then((data) => {
                if (!response.ok) {
                    throw new Error(data.error || data.message || `fix ${response.status}`);
                }
                return data;
            }))
            .then((data) => {
                const label = action === 'merge' ? 'Merged' : action === 'keep' ? 'Kept as Unmatched' : 'Ignored';
                showToast(`${label} duplicate${data.folder_path ? ` · ${data.folder_path}` : ''}`, 'success');
                return updateUnmatchedFolders();
            })
            .catch((err) => {
                showToast(err?.message || `Could not ${action} duplicate`, 'info');
            })
            .finally(() => {
                if (button) {
                    button.disabled = false;
                    button.removeAttribute('aria-busy');
                }
            });
    }

    /**
     * Soft Search name → Backend name endpoint when present.
     * Body: { search_name, display_name? }. Never renames on disk.
     */
    function saveAmendNaming(folderId, searchName, button, input) {
        if (!folderId) return;
        if (!searchName) {
            showToast('Enter a search name', 'info');
            return;
        }
        if (button) {
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');
        }
        const body = { search_name: searchName, display_name: searchName };
        const endpoints = [
            { url: `/api/unmatched_folders/${encodeURIComponent(folderId)}/name`, method: 'PATCH' },
            { url: `/api/unmatched_folders/${encodeURIComponent(folderId)}/name`, method: 'POST' },
            { url: `/api/unmatched_folders/${encodeURIComponent(folderId)}/amend_name`, method: 'POST' },
        ];

        function tryNext(index) {
            if (index >= endpoints.length) {
                unmatchedNameEndpointReady = false;
                if (input) {
                    input.dataset.original = searchName;
                    input.setAttribute('data-local-amended', '1');
                }
                const row = unmatchedTableBody.querySelector(`tr[data-folder-id="${CSS.escape(folderId)}"]`);
                const markBtns = row ? row.querySelectorAll('.mark-kind-btn') : [];
                markBtns.forEach((btn) => { btn.dataset.name = searchName; });
                showToast('Search name kept for Fix search (server not ready)', 'info');
                if (button) {
                    button.disabled = false;
                    button.removeAttribute('aria-busy');
                }
                return;
            }
            if (unmatchedNameEndpointReady === false && index === 0) {
                tryNext(endpoints.length);
                return;
            }
            const ep = endpoints[index];
            fetch(ep.url, {
                method: ep.method,
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                },
                body: JSON.stringify(body),
            })
                .then(async (response) => {
                    if (response.status === 404 || response.status === 405) {
                        tryNext(index + 1);
                        return;
                    }
                    const data = await response.json().catch(() => ({}));
                    if (!response.ok) {
                        throw new Error(data.error || data.message || `amend ${response.status}`);
                    }
                    unmatchedNameEndpointReady = true;
                    if (input) input.dataset.original = searchName;
                    const row = unmatchedTableBody.querySelector(`tr[data-folder-id="${CSS.escape(folderId)}"]`);
                    const markBtns = row ? row.querySelectorAll('.mark-kind-btn') : [];
                    markBtns.forEach((btn) => { btn.dataset.name = searchName; });
                    showToast(`Search name saved · “${searchName}”`, 'success');
                    if (button) {
                        button.disabled = false;
                        button.removeAttribute('aria-busy');
                    }
                })
                .catch((err) => {
                    showToast(err?.message || 'Could not save search name', 'info');
                    if (button) {
                        button.disabled = false;
                        button.removeAttribute('aria-busy');
                    }
                });
        }
        tryNext(0);
    }

    // Path popup — never navigate away to Auto Scan. Copy + optional companion open.
    function revealPath(path, button) {
        if (!path) return;

        if (button) {
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');
        }

        showOpenPathModal(path, {
            onDone: () => {
                if (button) {
                    button.disabled = false;
                    button.removeAttribute('aria-busy');
                }
            },
        });
    }

    function showOpenPathModal(path, { onDone } = {}) {
        const existing = document.getElementById('od-open-path-modal');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'od-open-path-modal';
        overlay.className = 'od-open-path-modal';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.innerHTML = `
          <div class="od-open-path-modal__panel">
            <div class="od-open-path-modal__toolbar">
              <h2>Folder path</h2>
              <button type="button" class="od-open-path-modal__close" aria-label="Close">×</button>
            </div>
            <p class="od-open-path-modal__path"><code></code></p>
            <div class="od-open-path-modal__actions">
              <button type="button" class="btn btn-primary btn-sm od-open-path-copy">Copy path</button>
              <button type="button" class="btn btn-outline-light btn-sm od-open-path-explorer">Open in file explorer</button>
            </div>
            <p class="od-open-path-modal__status" role="status"></p>
          </div>
        `;
        const code = overlay.querySelector('code');
        code.textContent = path;
        const statusEl = overlay.querySelector('.od-open-path-modal__status');

        function close() {
            overlay.remove();
            onDone?.();
        }

        overlay.addEventListener('click', (event) => {
            if (event.target === overlay) close();
        });
        overlay.querySelector('.od-open-path-modal__close').addEventListener('click', close);
        overlay.querySelector('.od-open-path-copy').addEventListener('click', () => {
            copyPathToClipboard(path).then(() => {
                statusEl.textContent = 'Path copied to clipboard';
                showToast('Path copied to clipboard', 'success');
            });
        });
        overlay.querySelector('.od-open-path-explorer').addEventListener('click', () => {
            statusEl.textContent = 'Queuing companion…';
            fetch('/api/client/commands', {
                method: 'POST',
                credentials: 'same-origin',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                },
                body: JSON.stringify({ game_uuid: '', action: 'open_path', path, select: true }),
            })
                .then((response) => {
                    if (!response.ok) {
                        return response.json().catch(() => ({})).then((data) => {
                            throw new Error(data.error || `open_path ${response.status}`);
                        });
                    }
                    statusEl.textContent = 'Queued open in file explorer for companion';
                    showToast('Queued open in file explorer', 'success');
                })
                .catch((err) => {
                    return copyPathToClipboard(path).then(() => {
                        statusEl.textContent = `${err.message || 'Open failed'} — path copied as fallback`;
                        showToast('Path copied (explorer open unavailable)', 'info');
                    });
                });
        });

        if (!document.getElementById('od-open-path-modal-style')) {
            const style = document.createElement('style');
            style.id = 'od-open-path-modal-style';
            style.textContent = `
              .od-open-path-modal{position:fixed;inset:0;z-index:2000;display:flex;align-items:center;justify-content:center;padding:1rem;background:rgba(5,7,10,.82)}
              .od-open-path-modal__panel{width:min(40rem,100%);display:flex;flex-direction:column;gap:.75rem;padding:1rem;border-radius:12px;border:1px solid rgba(255,255,255,.14);background:#141820;color:#f2f4f8}
              .od-open-path-modal__toolbar{display:flex;justify-content:space-between;align-items:center;gap:.75rem}
              .od-open-path-modal__toolbar h2{margin:0;font-size:1.05rem}
              .od-open-path-modal__close{width:2.2rem;height:2.2rem;border-radius:999px;border:1px solid rgba(255,255,255,.14);background:#1c2230;color:#f2f4f8;font-size:1.35rem;cursor:pointer}
              .od-open-path-modal__path{margin:0;padding:.75rem;border-radius:8px;background:#1c2230;word-break:break-all}
              .od-open-path-modal__actions{display:flex;flex-wrap:wrap;gap:.5rem}
              .od-open-path-modal__status{margin:0;font-size:.85rem;opacity:.8;min-height:1.2em}
            `;
            document.head.appendChild(style);
        }

        document.body.appendChild(overlay);
    }

    function showDupeComparePopout(compareEl) {
        const existing = document.getElementById('od-dupe-compare-modal');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'od-dupe-compare-modal';
        overlay.className = 'od-dupe-compare-modal';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-labelledby', 'od-dupe-compare-modal-title');
        overlay.innerHTML =
            '<div class="od-dupe-compare-modal__panel">' +
              '<div class="od-dupe-compare-modal__toolbar">' +
                '<h2 id="od-dupe-compare-modal-title">Folder vs library game</h2>' +
                '<button type="button" class="od-dupe-compare-modal__close" aria-label="Close">×</button>' +
              '</div>' +
              '<div class="od-dupe-compare-modal__body"></div>' +
            '</div>';

        const clone = compareEl.cloneNode(true);
        const clonePop = clone.querySelector('.unmatched-dupe-compare__pop');
        if (clonePop) clonePop.remove();
        overlay.querySelector('.od-dupe-compare-modal__body').appendChild(clone);

        function close() {
            overlay.remove();
            document.removeEventListener('keydown', onKey);
        }
        function onKey(event) {
            if (event.key === 'Escape') close();
        }

        overlay.addEventListener('click', function(event) {
            if (event.target === overlay) close();
        });
        overlay.querySelector('.od-dupe-compare-modal__close').addEventListener('click', close);
        document.addEventListener('keydown', onKey);
        document.body.appendChild(overlay);
        overlay.querySelector('.od-dupe-compare-modal__close').focus();
    }

    // Filtering functionality
    let currentFilter = 'all';
    let currentSearch = '';

    // Notification system
    function showSuccessNotification(message) {
        // Remove any existing notification
        const existingNotification = document.querySelector('.success-notification');
        if (existingNotification) {
            existingNotification.remove();
        }

        // Create new notification
        const notification = document.createElement('div');
        notification.className = 'success-notification';
        notification.innerHTML = `
            ✓ <span>${message}</span>
        `;

        document.body.appendChild(notification);

        // Show notification
        setTimeout(() => notification.classList.add('show'), 10);

        // Hide and remove notification after 3 seconds
        setTimeout(() => {
            notification.classList.add('hide');
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }

    // Sorting for this table moved to js/od_sortable_table.js. The row-level
    // data-sort-* attributes below are still what it reads; only the sorting,
    // the header buttons and the indicator bookkeeping left this file.

    function filterUnmatchedRows() {
        const unmatchedRows = document.querySelectorAll('#unmatchedFoldersTableBody tr');
        let visibleCount = 0;

        unmatchedRows.forEach(row => {
            const status = row.getAttribute('data-status');
            const searchBlob = row.getAttribute('data-search-blob')
                || [
                    row.getAttribute('data-folder-path') || '',
                    row.getAttribute('data-library-name') || '',
                    row.getAttribute('data-platform-name') || '',
                ].join(' ');
            const matchReason = row.getAttribute('data-match-reason') || '';
            const suggestedKind = row.getAttribute('data-suggested-kind') || 'none';
            const leafType = row.getAttribute('data-leaf-type') || 'folder-leaf';
            const platformMismatch = row.getAttribute('data-platform-mismatch') === '1';
            const garbage = row.getAttribute('data-garbage') === '1';

            const statusMatch = currentFilter === 'all' || status === currentFilter;
            const searchMatch = currentSearch === '' || searchBlob.includes(currentSearch);
            const whyMatch = currentWhyFilter === 'all' || matchReason === currentWhyFilter;
            const kindMatch = currentKindFilter === 'all'
                || (currentKindFilter === 'none' ? suggestedKind === 'none' : suggestedKind === currentKindFilter);
            const leafMatch = currentLeafFilter === 'all' || leafType === currentLeafFilter;
            const triageMatch = currentTriageFilter === 'all'
                || (currentTriageFilter === 'platform-mismatch' && platformMismatch)
                || (currentTriageFilter === 'garbage' && garbage);

            let shouldShow = statusMatch && searchMatch && whyMatch && kindMatch && leafMatch && triageMatch;

            // Hide ignored items unless viewing "All" or "Ignored"
            if (status === 'Ignore' && currentFilter !== 'all' && currentFilter !== 'Ignore') {
                shouldShow = false;
            }

            if (shouldShow) {
                row.style.display = '';
                row.classList.remove('row-fade-out');
                visibleCount++;
            } else {
                row.style.display = 'none';
                const check = row.querySelector('.unmatched-row-check');
                if (check && check.checked) {
                    check.checked = false;
                    unmatchedSelectedIds.delete(String(check.value || ''));
                }
            }
        });

        updateResultsCounter(visibleCount, unmatchedRows.length);
        updateBatchBar();
        updateSelectAllState();
    }

    function updateResultsCounter(visible = null, total = null) {
        const resultsInfo = document.getElementById('resultsInfo');
        if (!resultsInfo) return;

        if (visible === null || total === null) {
            const unmatchedRows = document.querySelectorAll('#unmatchedFoldersTableBody tr');
            total = unmatchedRows.length;
            visible = Array.from(unmatchedRows).filter(row => row.style.display !== 'none').length;
        }

        const parts = [];
        if (currentFilter !== 'all') parts.push(currentFilter);
        if (unmatchedLibraryFilter) parts.push('library');
        if (unmatchedPlatformFilter) parts.push(`system:${unmatchedPlatformFilter}`);
        if (unmatchedRegionFilter) parts.push(`region:${unmatchedRegionFilter}`);
        if (currentWhyFilter !== 'all') parts.push(`why:${currentWhyFilter}`);
        if (currentKindFilter !== 'all') parts.push(`kind:${currentKindFilter}`);
        if (currentLeafFilter !== 'all') {
            parts.push(
                currentLeafFilter === 'file-leaf'
                    ? 'ROM files library'
                    : currentLeafFilter === 'folder-leaf'
                      ? 'Folder library'
                      : `layout:${currentLeafFilter}`,
            );
        }
        if (currentTriageFilter !== 'all') parts.push(`triage:${currentTriageFilter}`);
        const filterText = parts.length ? ` (${parts.join(' · ')})` : '';
        const searchText = currentSearch ? ` matching "${currentSearch}"` : '';
        const pageStart = unmatchedTotalCount ? unmatchedPageOffset + 1 : 0;
        const pageEnd = unmatchedPageOffset + visible;
        const totalLabel = unmatchedTotalCount || total;
        resultsInfo.textContent =
            `Showing ${pageStart}–${pageEnd} of ${totalLabel}${filterText}${searchText}`;
        updateUnmatchedPager();
    }

    function updateUnmatchedPager() {
        const pager = document.getElementById('unmatchedPager');
        const meta = document.getElementById('unmatchedPageMeta');
        const prev = document.getElementById('unmatchedPrevPage');
        const next = document.getElementById('unmatchedNextPage');
        if (!pager || !meta || !prev || !next) return;
        const total = unmatchedTotalCount || 0;
        const showPager = total > unmatchedPageLimit;
        pager.hidden = !showPager;
        const page = Math.floor(unmatchedPageOffset / unmatchedPageLimit) + 1;
        const pages = Math.max(1, Math.ceil(total / unmatchedPageLimit));
        meta.textContent = `Page ${page} of ${pages}`;
        prev.disabled = unmatchedPageOffset <= 0;
        next.disabled = unmatchedPageOffset + unmatchedPageLimit >= total;
    }

    function refetchUnmatchedFromStart() {
        unmatchedPageOffset = 0;
        lastUnmatchedSignature = '';
        return updateUnmatchedFolders().then(() => filterUnmatchedRows());
    }

    function updateBatchBar() {
        const bar = document.getElementById('unmatchedBatchBar');
        const countEl = document.getElementById('unmatchedBatchCount');
        if (!bar || !countEl) return;
        const n = unmatchedSelectedIds.size;
        countEl.textContent = `${n} selected`;
        bar.hidden = n === 0;
    }

    function updateSelectAllState() {
        const selectAll = document.getElementById('unmatchedSelectAll');
        if (!selectAll) return;
        const visibleChecks = Array.from(
            document.querySelectorAll('#unmatchedFoldersTableBody tr:not([style*="display: none"]) .unmatched-row-check, #unmatchedFoldersTableBody tr:not([hidden]) .unmatched-row-check'),
        ).filter((el) => {
            const row = el.closest('tr');
            return row && row.style.display !== 'none';
        });
        const checked = visibleChecks.filter((el) => el.checked).length;
        selectAll.checked = visibleChecks.length > 0 && checked === visibleChecks.length;
        selectAll.indeterminate = checked > 0 && checked < visibleChecks.length;
    }

    function visibleUnmatchedRows() {
        return Array.from(document.querySelectorAll('#unmatchedFoldersTableBody tr')).filter(
            (row) => row.style.display !== 'none',
        );
    }

    function runBatchAction(action) {
        const ids = [...unmatchedSelectedIds];
        if (!ids.length) return;

        if (action === 'deselect') {
            unmatchedSelectedIds.clear();
            document.querySelectorAll('.unmatched-row-check').forEach((el) => { el.checked = false; });
            updateBatchBar();
            updateSelectAllState();
            return;
        }

        if (action === 'ignore_selected') {
            const ignoreIds = ids.filter((id) => {
                const row = document.querySelector(`tr[data-folder-id="${CSS.escape(id)}"]`);
                return row && row.getAttribute('data-status') !== 'Ignore';
            });
            if (!ignoreIds.length) {
                showToast('Select rows that are not already Ignored', 'info');
                return;
            }
            if (!confirm(`Ignore ${ignoreIds.length} selected entr${ignoreIds.length === 1 ? 'y' : 'ies'}?`)) return;
            showSpinner();
            softBatchPost(
                '/api/unmatched_folders/batch/ignore',
                { ids: ignoreIds },
                () => Promise.all(ignoreIds.map((id) => fetch(`/toggle_ignore_status/${encodeURIComponent(id)}`, {
                    method: 'POST',
                    headers: CSRFUtils.getHeaders({
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    }),
                }).then((r) => r.json().catch(() => ({})).then((data) => ({ ok: r.ok && data.status === 'success', data }))))),
            )
                .then((results) => {
                    const ok = Array.isArray(results)
                        ? results.filter((r) => r.ok).length
                        : (results?.ignored ?? results?.ok_count ?? ignoreIds.length);
                    showSuccessNotification(`Ignored ${ok}/${ignoreIds.length} selected`);
                    unmatchedSelectedIds.clear();
                    return updateUnmatchedFolders();
                })
                .catch((err) => {
                    console.error(err);
                    showToast(err?.message || 'Batch ignore failed', 'info');
                })
                .finally(() => hideSpinner());
            return;
        }

        if (action === 'clear') {
            if (!confirm(`Clear ${ids.length} selected unmatched entr${ids.length === 1 ? 'y' : 'ies'}?`)) return;
            showSpinner();
            softBatchPost('/api/unmatched_folders/batch/clear', { ids }, () =>
                Promise.all(ids.map((id) => fetch(`/clear_unmatched_entry/${encodeURIComponent(id)}`, {
                    method: 'POST',
                    headers: CSRFUtils.getHeaders({
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                    }),
                }).then((r) => r.json().catch(() => ({}))))),
            )
                .then((result) => {
                    const n = result?.cleared ?? result?.ok_count ?? ids.length;
                    showSuccessNotification(`Cleared ${n} selected`);
                    unmatchedSelectedIds.clear();
                    return updateUnmatchedFolders();
                })
                .catch((err) => {
                    console.error(err);
                    showToast(err?.message || 'Batch clear failed', 'info');
                })
                .finally(() => hideSpinner());
            return;
        }

        if (action.startsWith('mark_')) {
            const itemKind = action.replace('mark_', '');
            showSpinner();
            softBatchPost(
                '/api/unmatched_folders/batch/mark_kind',
                { ids, item_kind: itemKind },
                () => Promise.all(ids.map((id) => {
                    const row = document.querySelector(`tr[data-folder-id="${CSS.escape(id)}"]`);
                    const nameInput = row && row.querySelector('.unmatched-amend__input');
                    const name = nameInput ? String(nameInput.value || '').trim() : '';
                    const body = { item_kind: itemKind };
                    if (name) body.name = name;
                    return fetch(`/api/unmatched_folders/${encodeURIComponent(id)}/mark_kind`, {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': csrfToken,
                        },
                        body: JSON.stringify(body),
                    }).then((r) => r.json().catch(() => ({})).then((data) => ({ ok: r.ok, data })));
                })),
            )
                .then((results) => {
                    const ok = Array.isArray(results)
                        ? results.filter((r) => r.ok).length
                        : (results?.updated ?? results?.ok_count ?? ids.length);
                    showToast(`Marked ${ok}/${ids.length} as ${itemKind}`, ok ? 'success' : 'info');
                    unmatchedSelectedIds.clear();
                    return updateUnmatchedFolders();
                })
                .catch((err) => {
                    console.error(err);
                    showToast(err?.message || 'Batch mark kind failed', 'info');
                })
                .finally(() => hideSpinner());
            return;
        }

        if (action === 'merge' || action === 'keep' || action === 'ignore') {
            const dupIds = ids.filter((id) => {
                const row = document.querySelector(`tr[data-folder-id="${CSS.escape(id)}"]`);
                return row && row.getAttribute('data-status') === 'Duplicate';
            });
            if (!dupIds.length) {
                showToast('Select Duplicate rows for Merge / Keep / Ignore', 'info');
                return;
            }
            showSpinner();
            softBatchPost(
                '/api/unmatched_folders/batch/fix',
                { ids: dupIds, action },
                () => Promise.all(dupIds.map((id) => fetch(`/api/unmatched_folders/${encodeURIComponent(id)}/fix`, {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken,
                    },
                    body: JSON.stringify({ action }),
                }).then((r) => r.json().catch(() => ({})).then((data) => ({ ok: r.ok, data }))))),
            )
                .then((results) => {
                    const ok = Array.isArray(results)
                        ? results.filter((r) => r.ok).length
                        : (results?.updated ?? results?.ok_count ?? dupIds.length);
                    showToast(`Duplicate ${action}: ${ok}/${dupIds.length}`, ok ? 'success' : 'info');
                    unmatchedSelectedIds.clear();
                    return updateUnmatchedFolders();
                })
                .catch((err) => {
                    console.error(err);
                    showToast(err?.message || `Batch ${action} failed`, 'info');
                })
                .finally(() => hideSpinner());
        }
    }

    /** Prefer Backend batch route; on 404 fall back to per-id fan-out. */
    function softBatchPost(url, body, fallbackFn) {
        return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken,
            },
            body: JSON.stringify(body),
        }).then(async (response) => {
            if (response.status === 404 || response.status === 405) {
                return fallbackFn();
            }
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data.error || data.message || `batch ${response.status}`);
            }
            return data;
        });
    }

    // Keep the Export CSV/JSON links in sync with whichever filters are active.
    function updateExportLinks() {
        syncUnmatchedExportLinks();
    }

    function setupUnmatchedExportPop() {
        const toggle = document.getElementById('unmatchedExportToggle');
        const menu = document.getElementById('unmatchedExportMenu');
        if (!toggle || !menu || toggle.dataset.wired) return;
        toggle.dataset.wired = 'true';
        const close = () => {
            menu.hidden = true;
            toggle.setAttribute('aria-expanded', 'false');
            toggle.classList.remove('is-on');
        };
        const open = () => {
            syncUnmatchedExportLinks();
            menu.hidden = false;
            toggle.setAttribute('aria-expanded', 'true');
            toggle.classList.add('is-on');
        };
        toggle.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            if (menu.hidden) open();
            else close();
        });
        document.addEventListener('click', (event) => {
            if (!menu.hidden && !event.target.closest('#unmatchedExportPop')) close();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') close();
        });
    }

    function setupUnmatchedFilters() {
        setupUnmatchedExportPop();

        // Filter button event listeners — server-backed status refetch (pagination)
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                currentFilter = this.getAttribute('data-filter');
                refetchUnmatchedFromStart();
                updateExportLinks();
            });
        });

        document.querySelectorAll('[data-why-filter]').forEach((btn) => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('[data-why-filter]').forEach((b) => b.classList.remove('active'));
                this.classList.add('active');
                currentWhyFilter = this.getAttribute('data-why-filter') || 'all';
                refetchUnmatchedFromStart();
            });
        });

        document.querySelectorAll('[data-kind-filter]').forEach((btn) => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('[data-kind-filter]').forEach((b) => b.classList.remove('active'));
                this.classList.add('active');
                currentKindFilter = this.getAttribute('data-kind-filter') || 'all';
                refetchUnmatchedFromStart();
            });
        });

        document.querySelectorAll('[data-leaf-filter]').forEach((btn) => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('[data-leaf-filter]').forEach((b) => b.classList.remove('active'));
                this.classList.add('active');
                currentLeafFilter = this.getAttribute('data-leaf-filter') || 'all';
                filterUnmatchedRows();
            });
        });

        document.querySelectorAll('[data-triage-filter]').forEach((btn) => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('[data-triage-filter]').forEach((b) => b.classList.remove('active'));
                this.classList.add('active');
                currentTriageFilter = this.getAttribute('data-triage-filter') || 'all';
                filterUnmatchedRows();
            });
        });

        const librarySelect = document.getElementById('unmatchedLibraryFilter');
        if (librarySelect) {
            librarySelect.addEventListener('change', () => {
                unmatchedLibraryFilter = librarySelect.value || '';
                refetchUnmatchedFromStart();
            });
        }
        const platformSelect = document.getElementById('unmatchedPlatformFilter');
        if (platformSelect) {
            platformSelect.addEventListener('change', () => {
                unmatchedPlatformFilter = platformSelect.value || '';
                refetchUnmatchedFromStart();
            });
        }
        const regionSelect = document.getElementById('unmatchedRegionFilter');
        if (regionSelect) {
            regionSelect.addEventListener('change', () => {
                unmatchedRegionFilter = regionSelect.value || '';
                refetchUnmatchedFromStart();
            });
        }
        const pageSizeSelect = document.getElementById('unmatchedPageSize');
        if (pageSizeSelect) {
            pageSizeSelect.addEventListener('change', () => {
                unmatchedPageLimit = Number(pageSizeSelect.value) || 150;
                refetchUnmatchedFromStart();
            });
        }
        const prevPage = document.getElementById('unmatchedPrevPage');
        if (prevPage) {
            prevPage.addEventListener('click', () => {
                unmatchedPageOffset = Math.max(0, unmatchedPageOffset - unmatchedPageLimit);
                lastUnmatchedSignature = '';
                updateUnmatchedFolders().then(() => filterUnmatchedRows());
            });
        }
        const nextPage = document.getElementById('unmatchedNextPage');
        if (nextPage) {
            nextPage.addEventListener('click', () => {
                unmatchedPageOffset += unmatchedPageLimit;
                lastUnmatchedSignature = '';
                updateUnmatchedFolders().then(() => filterUnmatchedRows());
            });
        }

        // Search input — client filter immediate; soft q= goes out on list refresh
        const searchInput = document.getElementById('unmatchedSearch');
        if (searchInput) {
            let searchTimer = null;
            searchInput.addEventListener('input', function() {
                currentSearch = this.value.toLowerCase().trim();
                filterUnmatchedRows();
                updateExportLinks();
                clearTimeout(searchTimer);
                searchTimer = setTimeout(() => refetchUnmatchedFromStart(), 350);
            });
            searchInput.addEventListener('keydown', function(event) {
                if (event.key !== 'Enter') return;
                event.preventDefault();
                refetchUnmatchedFromStart();
            });
        }

        const selectAll = document.getElementById('unmatchedSelectAll');
        if (selectAll) {
            selectAll.addEventListener('change', function() {
                const rows = visibleUnmatchedRows();
                rows.forEach((row) => {
                    const check = row.querySelector('.unmatched-row-check');
                    if (!check) return;
                    check.checked = selectAll.checked;
                    const id = String(check.value || '');
                    if (selectAll.checked) unmatchedSelectedIds.add(id);
                    else unmatchedSelectedIds.delete(id);
                });
                updateBatchBar();
                updateSelectAllState();
            });
        }

        const batchBar = document.getElementById('unmatchedBatchBar');
        if (batchBar && !batchBar.dataset.wired) {
            batchBar.addEventListener('click', (event) => {
                const btn = event.target.closest('[data-batch-action]');
                if (!btn) return;
                runBatchAction(btn.getAttribute('data-batch-action') || '');
            });
            batchBar.dataset.wired = 'true';
        }

        const reclassifyBtn = document.getElementById('reclassifyDuplicatesBtn');
        if (reclassifyBtn) {
            reclassifyBtn.addEventListener('click', function() {
                if (!confirm('Reclassify false Duplicate rows (cross-system, different region, or different titles) as Unmatched?')) {
                    return;
                }
                reclassifyBtn.disabled = true;
                fetch('/api/unmatched_folders/reclassify_duplicates', {
                    method: 'POST',
                    headers: CSRFUtils.getHeaders({
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    })
                })
                    .then(r => r.json())
                    .then(data => {
                        showSuccessNotification(
                            `Fixed ${data.changed_count || 0} false duplicates` +
                            (data.kept_count ? `; kept ${data.kept_count} true duplicates` : '')
                        );
                        return updateUnmatchedFolders();
                    })
                    .then(() => filterUnmatchedRows())
                    .catch(err => console.error('Reclassify failed:', err))
                    .finally(() => { reclassifyBtn.disabled = false; });
            });
        }

        const backfillKindBtn = document.getElementById('backfillSuggestedKindBtn');
        if (backfillKindBtn) {
            backfillKindBtn.addEventListener('click', function() {
                if (!confirm(
                    'Backfill Suggested kind hints from on-disk scan proposals for rows that still have null hints? Safe to re-run; only updates empty hints.',
                )) {
                    return;
                }
                backfillKindBtn.disabled = true;
                fetch('/api/unmatched_folders/backfill_suggested_kind', {
                    method: 'POST',
                    headers: CSRFUtils.getHeaders({
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    }),
                    body: JSON.stringify({}),
                })
                    .then(async (r) => {
                        const data = await r.json().catch(() => ({}));
                        if (!r.ok) {
                            throw new Error(data.error || data.message || 'Backfill failed');
                        }
                        return data;
                    })
                    .then(data => {
                        const updated = data.updated ?? 0;
                        const scanned = data.scanned ?? 0;
                        showSuccessNotification(
                            `Kind hints updated ${updated} of ${scanned} scanned` +
                            (data.skipped_no_sidecar
                                ? ` · ${data.skipped_no_sidecar} without proposal`
                                : ''),
                        );
                        return updateUnmatchedFolders();
                    })
                    .then(() => filterUnmatchedRows())
                    .catch(err => {
                        console.error('Backfill kind hints failed:', err);
                        showToast(err?.message || 'Backfill kind hints failed', 'error');
                    })
                    .finally(() => { backfillKindBtn.disabled = false; });
            });
        }
    }

    const refreshAllBtn = document.getElementById('refreshAllLibrariesBtn');
    if (refreshAllBtn) {
        refreshAllBtn.addEventListener('click', function() {
            if (!confirm('Refresh all libraries using each library’s last scan folder?')) {
                return;
            }

            function postRefreshAll(policy) {
                // Always send queue_policy + force_parallel (default queue on first attempt).
                const fields = buildScanQueueRequestFields(
                    policy == null ? SCAN_QUEUE_POLICY.QUEUE : policy,
                );
                refreshAllBtn.disabled = true;
                return fetch('/api/admin/libraries/refresh_all', {
                    method: 'POST',
                    headers: CSRFUtils.getHeaders({
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest',
                        Accept: 'application/json',
                    }),
                    body: JSON.stringify(fields),
                })
                    .then(r => r.json().then(data => ({ ok: r.ok, status: r.status, data })).catch(() => ({
                        ok: r.ok,
                        status: r.status,
                        data: { error: 'Refresh failed' },
                    })))
                    .then(({ ok, status, data }) => {
                        if (isAlreadyRunningReject(status, data) && policy == null) {
                            openScanConflictModal((chosen) => {
                                postRefreshAll(chosen);
                            });
                            return;
                        }
                        const toast = toastForScanStartResponse(data, ok);
                        showToast(toast.text, toast.variant);
                        if (ok) updateScanJobs();
                    })
                    .catch(err => {
                        console.error('Refresh all failed:', err);
                        showToast('Refresh all failed.', 'error');
                    })
                    .finally(() => { refreshAllBtn.disabled = false; });
            }

            if (scanBusy) {
                openScanConflictModal((policy) => postRefreshAll(policy));
                return;
            }
            postRefreshAll(null);
        });
    }

    // Set up filter controls
    setupUnmatchedFilters();
    updateExportLinks();

    // Jobs fetch always (scanBusy for Start Scan). Table/unmatched DOM only
    // when that pane is on screen; a live scan no longer rebuilds hidden tables.
    updateScanJobs();
    if (isScanPaneActive('unmatchedFolders')) {
        updateUnmatchedFolders();
    }

    let scanJobsPollTimer = null;
    function armScanJobsPoll() {
        window.clearTimeout(scanJobsPollTimer);
        const ms = scanJobsPollMs({
            busy: scanBusy,
            jobsPaneVisible: isScanJobsSurfaceVisible(),
        });
        scanJobsPollTimer = window.setTimeout(() => {
            if (document.visibilityState === 'hidden') {
                armScanJobsPoll();
                return;
            }
            Promise.resolve(updateScanJobs()).finally(() => armScanJobsPoll());
        }, ms);
    }

    let unmatchedPollTimer = null;
    function armUnmatchedPoll() {
        window.clearTimeout(unmatchedPollTimer);
        unmatchedPollTimer = window.setTimeout(() => {
            if (document.visibilityState === 'hidden' || !isScanPaneActive('unmatchedFolders')) {
                armUnmatchedPoll();
                return;
            }
            updateUnmatchedFolders()
                .then(() => filterUnmatchedRows())
                .finally(() => armUnmatchedPoll());
        }, 30000);
    }

    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            updateScanJobs();
            if (isScanPaneActive('unmatchedFolders')) {
                updateUnmatchedFolders();
            }
        }
    });
    armScanJobsPoll();
    armUnmatchedPoll();

    // Global functions for table interactions
    window.toggleIgnoreStatus = function(folderId, button) {
        const row = button.closest('tr');
        const currentStatus = row.getAttribute('data-status');
        const isBeingIgnored = currentStatus !== 'Ignore';

        // Show immediate visual feedback
        if (isBeingIgnored) {
            // If we're ignoring the item and not viewing "All" or "Ignored", hide it immediately
            if (currentFilter !== 'all' && currentFilter !== 'Ignore') {
                row.classList.add('row-fade-out');
                setTimeout(() => {
                    row.style.display = 'none';
                    updateResultsCounter();
                }, 300);
            }
        }

        fetch(`/toggle_ignore_status/${folderId}`, {
            method: 'POST',
            headers: CSRFUtils.getHeaders({
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                // Show success notification
                const action = isBeingIgnored ? 'ignored' : 'un-ignored';
                showSuccessNotification(`Folder ${action} successfully`);

                // Update table data in background
                updateUnmatchedFolders().then(() => {
                    // Reapply current filters after data refresh
                    filterUnmatchedRows();
                });
            } else {
                // If there was an error, restore the row if it was hidden
                if (isBeingIgnored && currentFilter !== 'all' && currentFilter !== 'Ignore') {
                    row.classList.remove('row-fade-out');
                    row.style.display = '';
                }
                console.error('Error toggling ignore status:', data.message);
            }
        })
        .catch(error => {
            // If there was an error, restore the row if it was hidden
            if (isBeingIgnored && currentFilter !== 'all' && currentFilter !== 'Ignore') {
                row.classList.remove('row-fade-out');
                row.style.display = '';
            }
            console.error('Error toggling ignore status:', error);
        });
    };

    window.clearEntry = function(folderId) {
        if (confirm('Remove this entry from the unmatched list?')) {
            const button = event.target.closest('button');
            const row = button.closest('tr');

            // Immediate visual feedback - fade out the row
            row.classList.add('row-fade-out');
            setTimeout(() => {
                row.style.display = 'none';
                updateResultsCounter();
            }, 300);

            fetch(`/clear_unmatched_entry/${folderId}`, {
                method: 'POST',
                headers: CSRFUtils.getHeaders({
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    showSuccessNotification('Entry removed successfully');

                    // Update table data in background
                    updateUnmatchedFolders().then(() => {
                        // Reapply current filters after data refresh
                        filterUnmatchedRows();
                    });
                } else {
                    // If there was an error, restore the row
                    row.classList.remove('row-fade-out');
                    row.style.display = '';
                    console.error('Error clearing entry:', data.message);
                }
            })
            .catch(error => {
                // If there was an error, restore the row
                row.classList.remove('row-fade-out');
                row.style.display = '';
                console.error('Error clearing entry:', error);
            });
        }
    };
});

// Folder browse setup function
/**
 * Populate the "Scan location" pickers from /api/library_roots.
 *
 * The picker only appears once there is a real choice to make: an install that
 * never set ONEIRODEX_LIBRARY_ROOTS has exactly one location, and a select with one
 * option is noise. A location that is configured but not currently mounted
 * still gets listed, marked unavailable — hiding it would turn "the NAS is
 * down" into "my library vanished".
 */
function loadScanLocations() {
    var $selects = $('.od-root-select');
    if (!$selects.length) {
        return;
    }

    $.ajax({
        url: '/api/library_roots',
        success: function(data) {
            var roots = (data && data.roots) || [];
            if (roots.length < 2) {
                return;
            }

            $selects.each(function() {
                var $select = $(this);
                var pathVar = $select.data('path-var');
                var $rootInput = $($select.data('root-input'));
                var $picker = $select.closest('.od-root-picker');
                var $hint = $picker.find('.od-root-picker__hint');

                $select.empty();
                roots.forEach(function(root) {
                    var label = root.label + (root.exists ? '' : ' — not mounted');
                    $select.append($('<option>').val(root.id).text(label).prop('selected', !!root.default));
                });

                /**
                 * Reflect the current selection into the hidden field and hint.
                 *
                 * `clearPath` is false on the initial pass on purpose. A folder
                 * path is relative to its root, so *switching* root invalidates
                 * it and it must go — but on load the field may already hold a
                 * path the server put there (a re-rendered form after a failed
                 * submit), and blanking that made the operator retype what they
                 * had just entered.
                 */
                function syncSelection(clearPath) {
                    var rootId = $select.val() || '';
                    var root = roots.filter(function(item) { return item.id === rootId; })[0];
                    $rootInput.val(rootId);
                    window[pathVar + 'Root'] = rootId;
                    if (clearPath) {
                        window[pathVar] = '';
                        $($select.data('path-input')).val('');
                    }
                    if (root && !root.exists) {
                        $hint.text('Not mounted right now: ' + root.path).prop('hidden', false);
                    } else if (root) {
                        $hint.text(root.path).prop('hidden', false);
                    } else {
                        $hint.prop('hidden', true);
                    }
                }

                $select.off('change.odRoots').on('change.odRoots', function () {
                    syncSelection(true);
                });
                syncSelection(false);
                $picker.prop('hidden', false);
            });
        },
        error: function(error) {
            // A missing roots endpoint (older server, or a 403) must not break
            // the folder browser: it keeps its historical single-root behaviour.
            console.error('Error fetching scan locations:', error);
        }
    });
}

function setupFolderBrowse(browseButtonId, folderContentsId, spinnerId, upButtonId, inputFieldId, currentPathVar) {
    // Store the initial library selection
    var initialLibrarySelection = $(inputFieldId).closest('form').find('select[name="library_uuid"]').val();
    
    $(browseButtonId).click(function() {
        window[currentPathVar] = ''; // Reset the current path
        // Re-read the picker on every open: the admin may have changed the
        // scan location since the last browse.
        var $rootSelect = $('.od-root-select[data-path-var="' + currentPathVar + '"]');
        window[currentPathVar + 'Root'] = $rootSelect.val() || '';
        $(upButtonId).hide(); // Initially hide the "Up" button
        // Preserve the library selection
        var librarySelect = $(inputFieldId).closest('form').find('select[name="library_uuid"]');
        if (!librarySelect.val() && initialLibrarySelection) {
            librarySelect.val(initialLibrarySelection);
        }
        fetchFolders('', folderContentsId, spinnerId, upButtonId, inputFieldId, currentPathVar);
    });

    $(upButtonId).click(function() {
        var segments = window[currentPathVar].split('/').filter(Boolean);
        if (segments.length > 0) {
            // Remove the last segment to go up one level
            segments.pop();
            if (segments.length > 0) {
                window[currentPathVar] = segments.join('/') + '/';
            } else {
                window[currentPathVar] = ''; // Reset to base directory if no segments left
            }
        } else {
            window[currentPathVar] = ''; // Already at base directory
        }

        fetchFolders(window[currentPathVar], folderContentsId, spinnerId, upButtonId, inputFieldId, currentPathVar);

        // Update the input field with the new current path
        $(inputFieldId).val(window[currentPathVar]);

        if (segments.length < 1) {
            $(upButtonId).hide();
        } else {
            $(upButtonId).show();
        }
    });
}

function fetchFolders(path, folderContentsId, spinnerId, upButtonId, inputFieldId, currentPathVar) {
    console.log("Fetching folders for path:", path);
    // Blocking overlay, not an icon beside the button (W27-D6). A small spinner
    // to the right of Browse read as a stuck button rather than as work, and it
    // shifted the row it sat in. The inline spinner stays as the fallback for
    // the case where the motif helper did not load, because losing the busy
    // signal entirely is worse than showing it in the old place.
    var $spinner = $(spinnerId);
    var usedOverlay = false;
    if (window.GtLoadingMotifs && window.GtLoadingMotifs.showBlocking) {
        window.GtLoadingMotifs.showBlocking('Reading folders…');
        usedOverlay = true;
    } else {
        $spinner.css('display', 'inline-flex').show();
    }

    function clearBusy() {
        if (usedOverlay) {
            window.GtLoadingMotifs.hideBlocking();
        } else {
            $spinner.hide();
        }
    }
    // The selected scan location travels with every listing request. Without
    // it the server falls back to the OS base folder, so browsing a NAS root
    // would silently drop back to /storage on the first click.
    var browseData = { path: path };
    var selectedRoot = window[currentPathVar + 'Root'];
    if (selectedRoot) {
        browseData.root = selectedRoot;
    }
    $.ajax({
        url: '/api/browse_folders_ss',
        data: browseData,
        success: function(data) {
            clearBusy();
            $(folderContentsId).empty();
            
            // Check if we're using the new response format or the old one
            const items = data.items || data;
            
            // Display warning if there were errors
            if (data.hasErrors) {
                $(folderContentsId).append(
                    $('<div class="alert alert-warning">').text(
                        `⚠ Some items (${data.skippedItems}) could not be accessed and were skipped.`
                    )
                );
            }
            
            items.forEach(function(item) {
                var itemElement;
                if (item.isDir) {
                    // Folder and file names come from the filesystem: text, never markup.
                    itemElement = $('<div>').text('📁 ' + item.name);
                    var fullPath = path + item.name + "/";
                    $(itemElement).addClass('folder-item').attr('data-path', fullPath);
                } else {
                    // Get file extension and appropriate icon
                    var ext = item.ext ? item.ext.toLowerCase() : '';
                    var iconClass = fileIcons[ext] || fileIcons['default'];
                    
                    // Format file size
                    var sizeText = formatFileSize(item.size);
                    
                    // Create file element with icon, name, and size
                    itemElement = $('<div>').text(item.name).append(
                        $('<span class="file-size">').text('(' + sizeText + ')')
                    );
                    $(itemElement)
                        .addClass('file-item')
                        .attr('title', item.name + ' - ' + sizeText)
                        .css('cursor', 'default');
                }
                $(folderContentsId).append(itemElement);
            });

            // Only attach click handlers to folders
            $('.folder-item').click(function() {
                var newPath = $(this).data('path');
                window[currentPathVar] = newPath; 
                fetchFolders(newPath, folderContentsId, spinnerId, upButtonId, inputFieldId, currentPathVar);
                $(inputFieldId).val(newPath); 
            });
            if (path) {
                $(upButtonId).show();
            } else {
                $(upButtonId).hide();
            }
        },
        error: function(error) {
            // Must clear on the failure path too, or a browse that 500s leaves
            // the page darkened with no way back.
            clearBusy();
            console.error("Error fetching folders:", error);
        }
    });
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const kilobyte = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(kilobyte));
    return parseFloat((bytes / Math.pow(kilobyte, i)).toFixed(2)) + ' ' + sizes[i];
}

/** Scan Filters tab — kind toggle, dir: prefix, quick-add chips (Wave 3). */
(function initScanFiltersExplainUi() {
    const DIR_PREFIX = 'dir:';
    const form = document.getElementById('odScanFilterForm');
    if (!form) return;

    const rawInput = document.getElementById('filter_pattern_raw');
    const hiddenInput = document.getElementById('filter_pattern');
    const dirPrefixEl = document.getElementById('odFilterDirPrefix');
    const labelEl = document.getElementById('odFilterPatternLabel');
    const hintEl = document.getElementById('odFilterPatternHint');
    const caseRow = document.getElementById('odFilterCaseRow');
    const caseSelect = document.getElementById('case_sensitive');
    const modalEl = document.getElementById('addFilterModal');

    const COPY = {
        name: {
            label: 'Tag to strip',
            placeholder: 'e.g. GOG',
            hint: 'Stored as the tag only. Scan strips -tag and .tag from folder names.',
        },
        dir: {
            label: 'Folder glob',
            placeholder: 'e.g. OpenVR* or _MyTools',
            hint: 'Saved as dir:… Skip matching folder basenames (case-insensitive fnmatch). Prefer prefix globs.',
        },
    };

    function selectedKind() {
        const checked = form.querySelector('input[name="gt_filter_kind"]:checked');
        return checked && checked.value === 'dir' ? 'dir' : 'name';
    }

    function stripDirPrefix(value) {
        const text = String(value || '').trim();
        if (text.toLowerCase().indexOf(DIR_PREFIX) === 0) {
            return text.slice(DIR_PREFIX.length).trim();
        }
        return text;
    }

    function syncHiddenFromRaw() {
        if (!rawInput || !hiddenInput) return;
        const kind = selectedKind();
        const body = String(rawInput.value || '').trim();
        if (!body) {
            hiddenInput.value = '';
            return;
        }
        if (kind === 'dir') {
            const glob = stripDirPrefix(body);
            hiddenInput.value = glob ? (DIR_PREFIX + glob) : '';
        } else {
            hiddenInput.value = stripDirPrefix(body);
        }
    }

    function applyKindUi() {
        const kind = selectedKind();
        const copy = COPY[kind] || COPY.name;
        if (labelEl) labelEl.textContent = copy.label;
        if (rawInput) rawInput.placeholder = copy.placeholder;
        if (hintEl) hintEl.textContent = copy.hint;
        if (dirPrefixEl) {
            const show = kind === 'dir';
            dirPrefixEl.hidden = !show;
            dirPrefixEl.setAttribute('aria-hidden', show ? 'false' : 'true');
        }
        if (caseRow) {
            caseRow.hidden = kind === 'dir';
        }
        if (kind === 'dir' && caseSelect) {
            caseSelect.value = 'no';
        }
        if (rawInput) {
            rawInput.value = stripDirPrefix(rawInput.value);
        }
        syncHiddenFromRaw();
    }

    function fillFilterForm(kind, pattern, caseSensitive) {
        const kindRadio = form.querySelector(`input[name="gt_filter_kind"][value="${kind === 'dir' ? 'dir' : 'name'}"]`);
        if (kindRadio) kindRadio.checked = true;
        if (rawInput) rawInput.value = stripDirPrefix(pattern || '');
        if (caseSelect) caseSelect.value = caseSensitive === 'yes' ? 'yes' : 'no';
        applyKindUi();
    }

    form.querySelectorAll('input[name="gt_filter_kind"]').forEach((radio) => {
        radio.addEventListener('change', applyKindUi);
    });
    if (rawInput) {
        rawInput.addEventListener('input', syncHiddenFromRaw);
        rawInput.addEventListener('change', syncHiddenFromRaw);
    }
    form.addEventListener('submit', syncHiddenFromRaw);

    document.querySelectorAll('.od-scan-filters__chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            fillFilterForm(
                chip.getAttribute('data-od-filter-kind'),
                chip.getAttribute('data-od-filter-pattern'),
                chip.getAttribute('data-od-filter-case') || 'no'
            );
            if (modalEl && window.bootstrap && bootstrap.Modal) {
                bootstrap.Modal.getOrCreateInstance(modalEl).show();
            }
            if (rawInput) {
                rawInput.focus();
                rawInput.select();
            }
        });
    });

    if (modalEl) {
        modalEl.addEventListener('shown.bs.modal', () => {
            applyKindUi();
            if (rawInput && !rawInput.value) rawInput.focus();
        });
        modalEl.addEventListener('hidden.bs.modal', () => {
            fillFilterForm('name', '', 'no');
        });
    }

    applyKindUi();
})();
