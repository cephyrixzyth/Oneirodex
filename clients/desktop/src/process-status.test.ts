import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))
vi.mock('./config-store.js', () => ({ isTauriRuntime: () => true }))

import { invoke } from '@tauri-apps/api/core'
import { isProcessRunning } from './process-status.js'

const launchId = '5d283155-6b33-45c9-b9cf-a8e872dd0559'

describe('native process identity', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset().mockResolvedValue(true)
  })

  it('sends the launch identity alongside its PID', async () => {
    await expect(isProcessRunning(42, launchId)).resolves.toBe(true)
    expect(invoke).toHaveBeenCalledWith('is_process_running', { pid: 42, launchId })
  })

  it.each([undefined, '', 'old-generation'])(
    'refuses an absent or malformed identity %s',
    async (id) => {
      await expect(isProcessRunning(42, id)).resolves.toBe(false)
      expect(invoke).not.toHaveBeenCalled()
    },
  )

  it.each([0, -1, 1.5, Number.NaN, 0x1_0000_0000])('refuses an invalid PID %s', async (pid) => {
    await expect(isProcessRunning(pid, launchId)).resolves.toBe(false)
    expect(invoke).not.toHaveBeenCalled()
  })
})
