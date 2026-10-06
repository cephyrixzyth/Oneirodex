// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { OneirodexClient } from './api.js'
import { pickDownloadVersion } from './download.js'

const versions = [
  { uuid: 'base', kind: 'base', label: 'Base', is_default: true },
  { uuid: 'update', kind: 'update', label: 'Update', is_default: false },
]
const api = () => ({ downloads: { listGameVersions: vi.fn().mockResolvedValue({ versions }) } })

afterEach(() => document.body.replaceChildren())

describe('download version choice', () => {
  it.each(['Cancel', 'Escape', 'backdrop'])('preserves %s as cancellation', async (action) => {
    const pending = pickDownloadVersion(api() as unknown as OneirodexClient, 'game-1')
    await vi.waitFor(() => expect(document.querySelector('[role="dialog"]')).not.toBeNull())
    if (action === 'Cancel') {
      document.querySelector<HTMLButtonElement>('.od-version-cancel')!.click()
    } else if (action === 'Escape') {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    } else {
      document.querySelector('.od-version-overlay')!.dispatchEvent(new MouseEvent('mousedown'))
    }
    await expect(pending).resolves.toBeNull()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
  })

  it('keeps an explicit base choice distinct from cancellation', async () => {
    const pending = pickDownloadVersion(api() as unknown as OneirodexClient, 'game-1')
    await vi.waitFor(() => expect(document.querySelector('.od-version-confirm')).not.toBeNull())
    document.querySelector<HTMLButtonElement>('.od-version-confirm')!.click()
    await expect(pending).resolves.toEqual({ kind: 'base' })
  })

  it('preserves the selected update version', async () => {
    const pending = pickDownloadVersion(api() as unknown as OneirodexClient, 'game-1')
    await vi.waitFor(() => expect(document.querySelectorAll('.od-version-option')).toHaveLength(2))
    document.querySelectorAll<HTMLButtonElement>('.od-version-option')[1]!.click()
    document.querySelector<HTMLButtonElement>('.od-version-confirm')!.click()
    await expect(pending).resolves.toEqual({ kind: 'update', versionUuid: 'update' })
  })
})
