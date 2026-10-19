import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { getJson } from '../api/adminApi'
import { UnmatchedPage } from './UnmatchedPage'

vi.mock('../api/adminApi', () => ({
  getJson: vi.fn(),
  postJson: vi.fn(),
}))

afterEach(() => vi.resetAllMocks())

test('direct unmatched page retains review controls and links back to scan jobs', async () => {
  vi.mocked(getJson).mockImplementation(async (url) => {
    if (String(url) === '/api/unmatched/bad_match_reasons') return { ok: true, reasons: [] }
    return [
      {
        id: 42,
        folder_path: '/storage/review/Unmatched Sample',
        status: 'Duplicate',
        library_name: 'Review Library',
        platform_name: 'PCWIN',
      },
    ]
  })

  render(
    <MemoryRouter initialEntries={['/scan_management?active_tab=unmatched']}>
      <Routes>
        <Route path="/scan_management" element={<UnmatchedPage />} />
      </Routes>
    </MemoryRouter>,
  )

  expect(await screen.findByText('/storage/review/Unmatched Sample')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Return to scan jobs' })).toBeVisible()
  expect(screen.getByRole('link', { name: 'Return to scan jobs' })).toHaveAttribute(
    'href',
    '/admin/scan-jobs',
  )
})

test('shows one-time link success feedback passed from the identify form', async () => {
  vi.mocked(getJson).mockImplementation(async (url) => {
    if (String(url) === '/api/unmatched/bad_match_reasons') return { ok: true, reasons: [] }
    return []
  })

  render(
    <MemoryRouter
      initialEntries={[
        {
          pathname: '/scan_management',
          search: '?active_tab=unmatched',
          state: { linkSuccess: "Linked existing game 'Parity Game' to this folder." },
        },
      ]}
    >
      <Routes>
        <Route path="/scan_management" element={<UnmatchedPage />} />
      </Routes>
    </MemoryRouter>,
  )

  expect(
    await screen.findByText("Linked existing game 'Parity Game' to this folder."),
  ).toBeInTheDocument()
})
