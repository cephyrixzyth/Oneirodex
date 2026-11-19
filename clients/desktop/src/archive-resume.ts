import { invoke } from '@tauri-apps/api/core'

interface Receipt {
  etag: string
  total: number
}
interface Checkpoint {
  size: number
  sha256?: string
}
export async function resumeScope(identity: string[]): Promise<string> {
  const bytes = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(JSON.stringify(identity)),
  )
  return Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, '0')).join('')
}
export async function openArchiveCheckpoint(path: string, scope: string) {
  const key = 'od.archive.v1.' + scope
  const partial = path + '.' + scope + '.part'
  let receipt: Receipt | undefined
  try {
    const value = JSON.parse(localStorage.getItem(key) || 'null')
    if (
      value &&
      /^"sha256-[0-9a-f]{64}"$/.test(value.etag) &&
      Number.isSafeInteger(value.total) &&
      value.total > 0
    )
      receipt = value
  } catch {
    /* A missing or retired receipt starts a new transfer. */
  }
  const offset = receipt
    ? (await invoke<Checkpoint>('archive_checkpoint', { path: partial, verify: false })).size
    : 0
  return {
    partial,
    scope,
    receipt,
    offset,
    remember(value: Receipt) {
      try {
        localStorage.setItem(key, JSON.stringify(value))
      } catch {
        /* This download can finish without saving a restart receipt. */
      }
    },
    forget() {
      try {
        localStorage.removeItem(key)
      } catch {
        /* The next request also checks the partial file on disk. */
      }
    },
  }
}
