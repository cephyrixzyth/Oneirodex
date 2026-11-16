import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { useLibraryScanToasts } from './useLibraryScanToasts'
import { stubFetch } from '../testJsonResponse'
import { showToast } from '../utils/toast'

vi.mock('../utils/toast', () => ({
  showToast: vi.fn(),
}))

beforeEach(() => {
  sessionStorage.clear()
  vi.mocked(showToast).mockClear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

test('useLibraryScanToasts toasts library-added rows and soft-fails on error', async () => {
  const fetchMock = stubFetch(async () => {
    if (fetchMock.mock.calls.length <= 1) {
      return {
        ok: true,
        json: async () => ({
          notifications: [
            {
              id: 99,
              kind: 'library_games_added',
              title: '2 games added to Library Arcade',
            },
          ],
        }),
      }
    }
    throw new Error('offline')
  })

  const { unmount } = renderHook(() => useLibraryScanToasts({ intervalMs: 60_000 }))

  await waitFor(() => {
    expect(showToast).toHaveBeenCalledWith('2 games added to Library Arcade', 'success')
  })

  unmount()
  expect(fetchMock).toHaveBeenCalled()
})

test('useLibraryScanToasts stays quiet when endpoint is not ready', async () => {
  stubFetch(async () => ({ ok: false, status: 404, json: async () => ({}) }))

  renderHook(() => useLibraryScanToasts({ intervalMs: 60_000 }))

  await waitFor(() => {
    expect(fetch).toHaveBeenCalled()
  })
  expect(showToast).not.toHaveBeenCalled()
})

test('useLibraryScanToasts collapses more than five libraries to a count', async () => {
  const notifications = ['A', 'B', 'C', 'D', 'E', 'F'].map((library, i) => ({
    id: i + 1,
    kind: 'library_games_added',
    library,
    title: `1 games added to library ${library}`,
  }))
  stubFetch(async () => ({
    ok: true,
    json: async () => ({ notifications }),
  }))

  renderHook(() => useLibraryScanToasts({ intervalMs: 60_000 }))

  await waitFor(() => {
    expect(showToast).toHaveBeenCalledWith('6 notifications', 'success', { count: 6 })
  })
  expect(showToast).toHaveBeenCalledTimes(1)
})

test('useLibraryScanToasts limits scan notices on narrow screens', async () => {
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }))
  const notifications = ['A', 'B', 'C'].map((library, i) => ({
    id: i + 1,
    kind: 'library_games_added',
    library,
    title: `1 game added to library ${library}`,
  }))
  stubFetch(async () => ({
    ok: true,
    json: async () => ({ notifications }),
  }))

  renderHook(() => useLibraryScanToasts({ intervalMs: 60_000 }))

  await waitFor(() => {
    expect(showToast).toHaveBeenCalledWith('3 notifications', 'success', {
      count: 3,
      maxIndividual: 2,
    })
  })
  expect(showToast).toHaveBeenCalledTimes(1)
})
