import { invoke } from '@tauri-apps/api/core'

import { isTauriRuntime } from './config-store.js'

export function hasNativeLaunchIdentity(pid: number, launchId: unknown): launchId is string {
  return (
    Number.isInteger(pid) &&
    pid > 0 &&
    pid <= 0xffff_ffff &&
    typeof launchId === 'string' &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(launchId)
  )
}

export async function isProcessRunning(pid: number, launchId?: string): Promise<boolean> {
  if (!isTauriRuntime() || !hasNativeLaunchIdentity(pid, launchId)) {
    return false
  }

  return invoke<boolean>('is_process_running', { pid, launchId })
}
