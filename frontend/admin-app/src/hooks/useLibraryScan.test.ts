import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { postJsonResult } from '../api/adminApi'
import { showToast } from '../utils/toast'
import { useLibraryScan } from './useLibraryScan'

vi.mock('../api/adminApi', () => ({ postJsonResult: vi.fn() }))
vi.mock('../utils/toast', () => ({ showToast: vi.fn() }))

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

test('keeps rejected scan errors in persistent state when requested', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => [] }),
  )
  vi.mocked(postJsonResult).mockResolvedValue({
    ok: false,
    status: 400,
    data: {
      status: 'rejected',
      error: 'Invalid cron expression: cron must have 5 fields: minute hour dom month dow',
    },
  })

  const { result } = renderHook(() => useLibraryScan({ persistentErrors: true }))
  await act(async () => {
    await result.current.startScan({
      libraryUuid: 'lib-1',
      settings: { schedule: 'cron', schedule_cron: 'bad cron' },
    })
  })

  expect(result.current.scanError).toBe(
    'Invalid cron expression: cron must have 5 fields: minute hour dom month dow',
  )
  expect(showToast).not.toHaveBeenCalled()

  act(() => result.current.clearScanError())
  expect(result.current.scanError).toBe('')
})
