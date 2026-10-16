import { render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
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

  render(<UnmatchedPage />)

  expect(await screen.findByText('/storage/review/Unmatched Sample')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Return to scan jobs' })).toBeVisible()
  expect(screen.getByRole('link', { name: 'Return to scan jobs' })).toHaveAttribute(
    'href',
    '/admin/scan-jobs',
  )
})
