import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, test, vi } from 'vitest'
import { SettingsPage } from './SettingsPage'
import { SETTINGS_GROUPS } from '../components/navConfig'

function stubModuleStatus(payload: any, { ok = true, status = 200 } = {}) {
  const fetchMock = vi.fn(async (url) => {
    if (String(url).includes('/api/settings/module-status')) {
      return {
        ok,
        status,
        headers: new Headers({ 'content-type': 'application/json' }),
        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => payload,
      }
    }
    return {
      ok: false,
      status: 404,
      headers: new Headers({ 'content-type': 'application/json' }),

      text: async function () {
        return JSON.stringify(await this.json())
      },
      json: async () => ({}),
    }
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('SettingsPage module badges', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  test('renders on/off badges against the modules that report status', async () => {
    stubModuleStatus({
      ai: { on: false, label: 'Off' },
      storage: { on: true, label: 'On', detail: 'Apply off' },
    })

    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    )

    await waitFor(() => {
      expect(screen.getAllByTestId('settings-module-badge')).toHaveLength(1)
    })

    // Only the modules with a statusKey are badged — the rest of the hub
    // is plain links, which is why the count is asserted exactly.
    const badges = screen.getAllByTestId('settings-module-badge')
    expect(badges.filter((b) => b.className.includes('settings-shell-badge--on'))).toHaveLength(1)
    expect(badges.filter((b) => b.className.includes('settings-shell-badge--off'))).toHaveLength(0)
    // `detail` is how the hub says "helpers on, apply still off".
    expect(screen.getByText(/Apply off/)).toBeInTheDocument()

    // Badge beside the module title, not inside its title column.
    const storageBadge = badges.find((b) => b.textContent!.includes('Apply off'))
    expect(storageBadge!.closest('.od-settings-row__title')).toBeNull()
    expect(storageBadge!.closest('.od-settings-row')).not.toBeNull()
    await userEvent.setup().click(screen.getByRole('tab', { name: /Extend/ }))
    expect(screen.getByText('Off').closest('.od-settings-row')).not.toBeNull()
    expect(document.querySelectorAll('.od-settings-group.od-admin-panel')).toHaveLength(0)
    expect(document.querySelectorAll('.od-admin-panel.od-settings')).toHaveLength(1)
  })

  test('a failed status fetch leaves the hub links intact', async () => {
    stubModuleStatus({}, { ok: false, status: 500 })

    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    )

    expect(screen.getByText('Storage')).toBeInTheDocument()
    await userEvent.setup().click(screen.getByRole('tab', { name: /Play & emulation/ }))
    expect(await screen.findByText('Remote play')).toBeInTheDocument()
    expect(screen.queryByTestId('settings-module-badge')).not.toBeInTheDocument()
  })

  test('opens to Library & matching and keeps other settings behind section tabs', () => {
    stubModuleStatus({})
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    )
    expect(screen.getByRole('tab', { name: /Library & matching/ })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(screen.getByRole('tabpanel', { name: /Library & matching/ })).toBeInTheDocument()
    expect(screen.queryByText('Remote play')).not.toBeInTheDocument()
  })

  test('section keyboard navigation moves selection and focus and retains configured links', async () => {
    stubModuleStatus({})
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>,
    )
    const tabs = screen.getAllByRole('tab')
    tabs[0].focus()
    await user.keyboard('{ArrowRight}')
    expect(tabs[1]).toHaveFocus()
    expect(tabs[1]).toHaveAttribute('aria-selected', 'true')
    expect(tabs[0]).toHaveAttribute('tabindex', '-1')
    await user.keyboard('{End}')
    expect(tabs[tabs.length - 1]).toHaveFocus()
    await user.keyboard('{ArrowRight}')
    expect(tabs[0]).toHaveFocus()
    await user.keyboard('{ArrowLeft}')
    expect(tabs[tabs.length - 1]).toHaveFocus()
    await user.keyboard('{Home}')
    expect(tabs[0]).toHaveFocus()
    for (let index = 0; index < SETTINGS_GROUPS.length; index += 1) {
      await user.click(tabs[index])
      expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', tabs[index].id)
      expect(tabs[index]).toHaveAttribute('aria-selected', 'true')
      expect(screen.getAllByRole('tab').filter((tab) => tab.tabIndex === 0)).toHaveLength(1)
      for (const item of SETTINGS_GROUPS[index].items) {
        const link = screen.getByText(item.title).closest('a')
        expect(link).toHaveAttribute('href', item.to)
      }
    }
  })
})
