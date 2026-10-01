/**
 * Reveal a path in the OS file manager (Explorer / Finder / xdg-open).
 * Used for local install folders and queued web `open_path` commands.
 */

import { invoke } from '@tauri-apps/api/core'

import { isPathUnderRoot } from './path-guard.js'

export interface OpenPathResult {
  ok: true
  path: string
  revealed_as: 'file' | 'directory'
}

export interface OpenPathFailure {
  ok: false
  error: string
}

/**
 * Absolute Windows drive, UNC, or Unix absolute path (no relative / bare names).
 * Shape only: "absolute" is not "allowed" — `validateRevealPath` refuses UNC.
 */
export function isAbsoluteOsPath(path: string): boolean {
  const trimmed = path.trim()
  if (!trimmed) {
    return false
  }
  if (/^[a-zA-Z]:[\\/]/.test(trimmed)) {
    return true
  }
  if (trimmed.startsWith('\\\\') || trimmed.startsWith('//')) {
    return true
  }
  if (trimmed.startsWith('/')) {
    return true
  }
  return false
}

/**
 * UNC shares (`\\host\share`, `//host/share`, mixed separators) and the Win32 / NT
 * device namespaces (`\\?\`, `\\.\`, `\??\`). On Windows even an existence probe of
 * one of these opens an SMB connection and leaks the user's NTLM hash to the named
 * host — and the path of a queued `open_path` is chosen by the server.
 * Mirrors `is_network_or_device_path` in `src-tauri/src/lib.rs`.
 */
export function isNetworkOrDevicePath(path: string): boolean {
  return /^[\\/]{2}/.test(path) || path.startsWith('\\??\\') || path.startsWith('/??/')
}

/** Shown when a reveal path names a network share or a device. */
export const NETWORK_PATH_REFUSED =
  'Network (UNC) and device paths are blocked — map the share to a drive letter and use that path instead'

/**
 * Reject empty, relative, traversal-only, null/control chars, UNC / device, and
 * overlong paths before handing off to the native reveal command.
 */
export function validateRevealPath(
  raw: string,
): { ok: true; path: string } | { ok: false; error: string } {
  if (typeof raw !== 'string') {
    return { ok: false, error: 'Path must be a string' }
  }
  const path = raw.trim()
  if (!path) {
    return { ok: false, error: 'Path is required' }
  }
  if (path.length > 4096) {
    return { ok: false, error: 'Path is too long' }
  }
  if (/[\0\r\n]/.test(path)) {
    return { ok: false, error: 'Path contains invalid control characters' }
  }
  if (isNetworkOrDevicePath(path)) {
    return { ok: false, error: NETWORK_PATH_REFUSED }
  }
  if (!isAbsoluteOsPath(path)) {
    return { ok: false, error: 'Path must be absolute (drive letter or /…)' }
  }
  // Reject "C:\.." style escapes that resolve outside a drive root when paired with roots.
  if (/(^|[\\/])\.\.([\\/]|$)/.test(path)) {
    return { ok: false, error: 'Path must not contain .. segments' }
  }
  return { ok: true, path }
}

/**
 * When revealing a known local install, require the path under the installs root.
 * Library/unmatched server paths skip this (Backend must allowlist library roots).
 */
export function isRevealAllowedUnderRoots(path: string, allowedRoots: string[]): boolean {
  if (allowedRoots.length === 0) {
    return true
  }
  return allowedRoots.some((root) => isPathUnderRoot(path, root))
}

export async function revealPathInOs(
  rawPath: string,
  options: { allowedRoots?: string[]; select?: boolean } = {},
): Promise<OpenPathResult | OpenPathFailure> {
  const checked = validateRevealPath(rawPath)
  if (!checked.ok) {
    return checked
  }
  if (
    options.allowedRoots &&
    options.allowedRoots.length > 0 &&
    !isRevealAllowedUnderRoots(checked.path, options.allowedRoots)
  ) {
    return { ok: false, error: 'Path is outside allowed roots' }
  }

  try {
    const result = await invoke<{ path: string; revealed_as: 'file' | 'directory' }>(
      'reveal_path_in_os',
      {
        path: checked.path,
        select: options.select ?? true,
      },
    )
    return { ok: true, path: result.path, revealed_as: result.revealed_as }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    return { ok: false, error: message || 'Failed to open path in file manager' }
  }
}
