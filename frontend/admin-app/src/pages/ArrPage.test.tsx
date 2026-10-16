import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { ArrPage } from './ArrPage'
import { deleteJson, getJson, postJson, putJson } from '../api/adminApi'
import { confirmAction } from '@oneirodex/ui'

vi.mock('../api/adminApi', () => ({
  deleteJson: vi.fn(),
  getJson: vi.fn(),
  postJson: vi.fn(),
  putJson: vi.fn(),
}))
vi.mock('@oneirodex/ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@oneirodex/ui')>()
  return { ...actual, confirmAction: vi.fn() }
})
afterEach(() => {
  vi.resetAllMocks()
})

const moduleOn = { enabled: true, db_enabled: true, env_enabled: false }
const config = {
  prowlarr_url: '',
  prowlarr_api_key_set: true,
  jackett_url: '',
  jackett_api_key_set: false,
  qbittorrent_url: 'http://qbit.local:8080',
  qbittorrent_username: 'admin',
  qbittorrent_password_set: true,
  transmission_url: '',
  transmission_username: '',
  transmission_password_set: false,
  sabnzbd_url: '',
  sabnzbd_api_key_set: false,
  nzbget_url: '',
  nzbget_username: '',
  nzbget_password_set: false,
}

function setupEnabled() {
  vi.mocked(getJson).mockImplementation(async (url) => {
    if (url === '/api/arr/module') return moduleOn
    if (url === '/api/arr/status')
      return {
        connectors: [{ id: 'native_indexers', configured: true }],
        indexer_warnings: [],
        hardlink_pipeline_enabled: true,
        hardlink_helpers_enabled: true,
        hardlink_apply_allowed: false,
      }
    if (url === '/api/arr/indexers')
      return {
        indexers: [
          {
            id: 'one',
            name: 'Index one',
            protocol: 'torznab',
            url: 'https://example.test/api',
            ready: true,
            enabled: true,
            source: 'manual',
          },
        ],
        presets: [{ id: 'preset-one', name: 'Preset One', protocol: 'torznab' }],
      }
    if (url === '/api/arr/config') return config
    throw new Error(`Unexpected GET ${url}`)
  })
}

test('loads the native indexer registry without exposing saved secrets', async () => {
  setupEnabled()
  render(<ArrPage />)
  expect(await screen.findByRole('heading', { name: 'Arr module' })).toBeInTheDocument()
  expect(await screen.findByRole('row', { name: /Index one/ })).toBeInTheDocument()
  expect(screen.getAllByPlaceholderText('Saved — leave blank to keep')).toHaveLength(2)
  expect(screen.getByText(/Hardlink apply is disabled/)).toBeInTheDocument()
  expect(vi.mocked(getJson)).not.toHaveBeenCalledWith(expect.stringContaining('/api/arr/search'))
})

test('queues no external download before confirmation', async () => {
  setupEnabled()
  vi.mocked(getJson).mockImplementation(async (url) =>
    url === '/api/arr/module'
      ? moduleOn
      : url === '/api/arr/status'
        ? {
            connectors: [],
            indexer_warnings: [],
            hardlink_pipeline_enabled: false,
            hardlink_helpers_enabled: false,
            hardlink_apply_allowed: false,
          }
        : url === '/api/arr/indexers'
          ? { indexers: [], presets: [] }
          : url === '/api/arr/config'
            ? config
            : {
                results: [
                  {
                    title: 'Metroid',
                    indexer: 'Native',
                    seeders: 8,
                    download_url: 'https://example.test/download?id=1',
                    quality: { score: 40, allowed: true },
                  },
                ],
                warnings: [],
                excluded_by_quality: 0,
              },
  )
  vi.mocked(confirmAction).mockResolvedValue(false)
  render(<ArrPage />)
  await screen.findByText('No native indexers yet. Add one, import, or enable presets.')
  fireEvent.change(screen.getByLabelText('Game title'), { target: { value: 'Metroid' } })
  fireEvent.click(screen.getByRole('button', { name: 'Search' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Send to qBittorrent…' }))
  await waitFor(() => expect(confirmAction).toHaveBeenCalled())
  expect(postJson).not.toHaveBeenCalledWith('/api/arr/download', expect.anything())
})

test('requires a separate confirmation before deleting an indexer', async () => {
  setupEnabled()
  vi.mocked(confirmAction).mockResolvedValue(false)
  render(<ArrPage />)
  fireEvent.click(await screen.findByRole('button', { name: 'Delete Index one' }))
  await waitFor(() =>
    expect(confirmAction).toHaveBeenCalledWith(
      expect.objectContaining({ confirmLabel: 'Delete indexer' }),
    ),
  )
  expect(deleteJson).not.toHaveBeenCalled()
})

test('saves hub configuration without resending blank saved secrets', async () => {
  setupEnabled()
  vi.mocked(putJson).mockResolvedValue({ status: 'saved', config })
  render(<ArrPage />)
  const url = await screen.findByLabelText('Prowlarr URL')
  fireEvent.change(url, { target: { value: 'https://prowlarr.example.test' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save connector settings' }))
  await waitFor(() =>
    expect(putJson).toHaveBeenCalledWith(
      '/api/arr/config',
      expect.objectContaining({ prowlarr_url: 'https://prowlarr.example.test' }),
    ),
  )
  const sent = vi.mocked(putJson).mock.calls[0][1] as Record<string, unknown>
  expect(sent).not.toHaveProperty('prowlarr_api_key')
  expect(sent).not.toHaveProperty('qbittorrent_password')
})

test('previews hardlinks without writes and requires confirmation before apply', async () => {
  setupEnabled()
  vi.mocked(getJson).mockImplementation(async (url) =>
    url === '/api/arr/module'
      ? moduleOn
      : url === '/api/arr/status'
        ? {
            connectors: [],
            indexer_warnings: [],
            hardlink_pipeline_enabled: true,
            hardlink_helpers_enabled: true,
            hardlink_apply_allowed: true,
          }
        : url === '/api/arr/indexers'
          ? { indexers: [], presets: [] }
          : config,
  )
  vi.mocked(postJson).mockImplementation(async (url) =>
    url === '/api/arr/hardlink/preview'
      ? {
          apply_allowed: true,
          count: 1,
          proposals: [
            {
              name: 'Completed title',
              source: '/downloads/title.iso',
              dest: '/games/title.iso',
              preview: { would_succeed: true, reasons: [] },
            },
          ],
        }
      : { applied: [{ name: 'Completed title' }], skipped: [] },
  )
  vi.mocked(confirmAction).mockResolvedValue(false)
  render(<ArrPage />)
  fireEvent.change(await screen.findByLabelText('Library destination directory'), {
    target: { value: '/games' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Preview hardlinks' }))
  expect(await screen.findByRole('row', { name: /Completed title/ })).toBeInTheDocument()
  expect(postJson).toHaveBeenCalledWith('/api/arr/hardlink/preview', { library_dest_dir: '/games' })
  fireEvent.click(screen.getByRole('button', { name: 'Apply allowed proposals…' }))
  await waitFor(() =>
    expect(confirmAction).toHaveBeenCalledWith(
      expect.objectContaining({ confirmLabel: 'Apply hardlinks' }),
    ),
  )
  expect(postJson).not.toHaveBeenCalledWith('/api/arr/hardlink/apply', expect.anything())
  vi.mocked(confirmAction).mockResolvedValue(true)
  fireEvent.click(screen.getByRole('button', { name: 'Apply allowed proposals…' }))
  await waitFor(() =>
    expect(postJson).toHaveBeenCalledWith(
      '/api/arr/hardlink/apply',
      expect.objectContaining({ only_ok: true }),
    ),
  )
})
