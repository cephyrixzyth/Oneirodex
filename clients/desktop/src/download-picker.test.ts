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
  it('names the version group, contains Tab focus, and restores the launcher focus', async () => {
    const launcher = document.createElement('button')
    launcher.textContent = 'Install game'
    document.body.append(launcher)
    launcher.focus()

    const pending = pickDownloadVersion(api() as unknown as OneirodexClient, 'game-1')
    await vi.waitFor(() => expect(document.querySelector('[role="dialog"]')).not.toBeNull())

    const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!
    const group = dialog.querySelector<HTMLElement>('[role="radiogroup"]')!
    const options = dialog.querySelectorAll<HTMLButtonElement>('.od-version-option')
    const cancel = dialog.querySelector<HTMLButtonElement>('.od-version-cancel')!
    const confirm = dialog.querySelector<HTMLButtonElement>('.od-version-confirm')!
    expect(group.getAttribute('aria-label')).toBe('Available download versions')
    expect(document.activeElement).toBe(options[0])

    confirm.focus()
    confirm.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true }))
    expect(document.activeElement).toBe(options[0])

    options[0]!.focus()
    options[0]!.dispatchEvent(
      new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true }),
    )
    expect(document.activeElement).toBe(confirm)

    cancel.click()
    await expect(pending).resolves.toBeNull()
    expect(document.activeElement).toBe(launcher)
  })

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
