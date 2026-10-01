/**
 * Network shares the user trusts for "open path".
 *
 * A queued `open_path` comes from the server, and opening a UNC path makes
 * Windows authenticate to the host it names — handing over the user's NTLM hash —
 * so UNC paths are refused unless their share is listed here. A Windows-hosted
 * server is told to use UNC library roots (`\\nas\roms`), and only the person at
 * this PC can say which of those they trust.
 *
 * The list lives on this PC (`trusted_shares.json`) and is enforced by the native
 * `reveal_path_in_os` command, which reads it itself: nothing in the webview, and
 * nothing a server sends, can widen it. This module is only the editor's plumbing.
 */

import { invoke } from '@tauri-apps/api/core'

import { isTauriRuntime } from './config-store.js'

/** One share per line; blank lines are ignored. UNC paths may contain spaces, so no other separator. */
export function parseTrustedShares(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line !== '')
}

export function formatTrustedShares(roots: string[]): string {
  return roots.join('\n')
}

export async function loadTrustedShares(): Promise<string[]> {
  if (!isTauriRuntime()) {
    return []
  }
  return invoke<string[]>('load_trusted_shares')
}

/**
 * Save the list. The native side validates every entry (it must look like
 * `\\server\share`) and rejects the whole save on one bad entry; the error text
 * names it. Resolves with the canonical list that was stored.
 */
export async function saveTrustedShares(roots: string[]): Promise<string[]> {
  if (!isTauriRuntime()) {
    return roots
  }
  try {
    return await invoke<string[]>('save_trusted_shares', { roots })
  } catch (error) {
    throw new Error(error instanceof Error ? error.message : String(error))
  }
}
