import { expect, test, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { getJson } from '../api/adminApi'
import { IntegrationsPage } from './IntegrationsPage'
vi.mock('../api/adminApi', () => ({ getJson: vi.fn() }))
vi.mock('../components/RetroAchievementsSettingsPanel', () => ({
  RetroAchievementsSettingsPanel: () => null,
}))

function CurrentRoute() {
  const { pathname, hash } = useLocation()
  return (
    <output data-testid="current-route">
      {pathname}
      {hash}
    </output>
  )
}

test('legacy React inventory fragment resolves to one OIDC form panel', async () => {
  vi.mocked(getJson).mockImplementation(async (url) =>
    url.includes('oidc')
      ? {
          settings: {
            oidc_enabled: false,
            oidc_display_name: 'SSO',
            oidc_issuer_url: '',
            oidc_client_id: '',
            oidc_client_secret_configured: false,
            oidc_redirect_uri: '',
            oidc_scopes: 'openid email profile',
            oidc_role_claim: 'groups',
            oidc_role_map: {},
          },
          readiness: { ready: false, message: 'OIDC is not ready.', missing: [] },
        }
      : { integrations: [], count: 0 },
  )
  const { container } = render(
    <MemoryRouter initialEntries={['/admin/integrations#oidc']}>
      <IntegrationsPage />
    </MemoryRouter>,
  )
  expect(await screen.findByRole('heading', { name: 'OIDC / SSO' })).toBeInTheDocument()
  expect(container.querySelectorAll('#oidc')).toHaveLength(1)
  expect(screen.getByLabelText('Issuer URL')).toBeInTheDocument()
})

test('internal integration destinations use router navigation and external inventory stays external', async () => {
  vi.mocked(getJson).mockImplementation(async (url) => {
    if (url.includes('inventory')) {
      return {
        integrations: [
          {
            id: 'internal-provider',
            name: 'Internal provider',
            category: 'metadata',
            settings_href: '/admin/igdb_settings',
          },
          {
            id: 'external-docs',
            name: 'External provider docs',
            category: 'metadata',
            admin_href: 'https://example.test/provider',
          },
        ],
        count: 2,
      }
    }
    if (url.includes('oidc')) {
      return {
        settings: {
          oidc_enabled: false,
          oidc_display_name: 'SSO',
          oidc_issuer_url: '',
          oidc_client_id: '',
          oidc_client_secret_configured: false,
          oidc_redirect_uri: '',
          oidc_scopes: 'openid email profile',
          oidc_role_claim: 'groups',
          oidc_role_map: {},
        },
        readiness: { ready: false, message: 'OIDC is not ready.', missing: [] },
      }
    }
    return { integrations: [], count: 0 }
  })

  render(
    <MemoryRouter initialEntries={['/admin/integrations']}>
      <IntegrationsPage />
      <CurrentRoute />
    </MemoryRouter>,
  )

  const currentRoute = screen.getByTestId('current-route')
  fireEvent.click(await screen.findByRole('link', { name: /IGDB/ }))
  await waitFor(() => expect(currentRoute).toHaveTextContent('/admin/igdb_settings'))

  fireEvent.click(screen.getByRole('link', { name: /Artwork & secondary/ }))
  await waitFor(() => expect(currentRoute).toHaveTextContent('/admin/integrations#artwork'))

  fireEvent.click(await screen.findByRole('link', { name: /Internal provider/ }))
  await waitFor(() => expect(currentRoute).toHaveTextContent('/admin/igdb_settings'))
  expect(screen.getByRole('link', { name: 'External provider docs' })).toHaveAttribute(
    'href',
    'https://example.test/provider',
  )
})

test('provider inventory offers Retry and displays refreshed rows', async () => {
  let inventoryCalls = 0
  vi.mocked(getJson).mockImplementation(async (url) => {
    if (url.includes('oidc'))
      return {
        settings: {
          oidc_enabled: false,
          oidc_display_name: 'SSO',
          oidc_issuer_url: '',
          oidc_client_id: '',
          oidc_client_secret_configured: false,
          oidc_redirect_uri: '',
          oidc_scopes: 'openid email profile',
          oidc_role_claim: 'groups',
          oidc_role_map: {},
        },
        readiness: { ready: false, message: 'OIDC is not ready.', missing: [] },
      }
    if (url.includes('inventory')) {
      inventoryCalls += 1
      if (inventoryCalls === 1) throw new Error('Offline')
      return {
        integrations: [
          { id: 'fixture', name: 'Review provider', category: 'metadata', status: 'available' },
        ],
        count: 1,
      }
    }
    return { username: null, has_key: false, username_source: null, key_source: null }
  })
  render(
    <MemoryRouter>
      <IntegrationsPage />
    </MemoryRouter>,
  )
  fireEvent.click(await screen.findByRole('button', { name: 'Retry provider inventory' }))
  expect(await screen.findByText('Review provider')).toBeInTheDocument()
  await waitFor(() => expect(inventoryCalls).toBe(2))
})
