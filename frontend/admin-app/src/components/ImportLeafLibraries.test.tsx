import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { ImportLeafLibraries } from './ImportLeafLibraries'
import {
  IMPORT_LEAF_PREVIEW_URL,
  LIBRARY_ADD_URL,
  LIBRARY_SCAN_URL,
} from '../api/proposeLeafLibrariesApi'

/** userEvent.type treats `{` as a key descriptor — set paste payloads directly. */
function setPasteValue(label: any, value: any) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } })
}

const CANDIDATES = [
  {
    path: '/storage/games/Switch',
    suggested_name: 'Nintendo Switch',
    platform: 'SWITCH',
    scan_mode: 'folders',
    scan_depth: 1,
    reason: 'csv/json import preview',
    source_index: 0,
  },
  {
    path: '/storage/games/PSX/ROMs',
    suggested_name: 'PlayStation (PSX)',
    platform: 'PSX',
    scan_mode: 'files',
    scan_depth: 1,
    reason: 'csv/json import preview',
    source_index: 1,
  },
]

const ROW_ERRORS = [
  {
    index: 2,
    path: '/storage/games/NINTENDO',
    code: 'family_parent_rejected',
    message: 'Refused family/mega-lib parent "NINTENDO"',
  },
]

describe('ImportLeafLibraries', () => {
  beforeEach(() => {
    document.head.innerHTML = '<meta name="csrf-token" content="test-csrf">'
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  test('preview → multi-select → confirm posts create then scan (never on preview)', async () => {
    const user = userEvent.setup()

    const fetchMock = vi.fn(async (url, opts) => {
      const href = String(url)
      if (href.includes(IMPORT_LEAF_PREVIEW_URL)) {
        expect(opts?.method).toBe('POST')
        const body = JSON.parse(opts.body)
        expect(Array.isArray(body)).toBe(true)
        expect(body[0].platform).toBe('SWITCH')
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => ({
            status: 'ok',
            auto_create: false,
            count: 2,
            error_count: 1,
            create_hint: 'Preview only — never auto-creates.',
            candidates: CANDIDATES,
            errors: ROW_ERRORS,
          }),
        }
      }
      if (href.includes(LIBRARY_ADD_URL)) {
        expect(opts?.method).toBe('POST')
        const form = opts.body
        expect(form.get('name')).toBe('Nintendo Switch')
        expect(form.get('platform')).toBe('SWITCH')
        expect(form.get('scan_depth')).toBe('1')
        expect(form.get('csrf_token')).toBe('test-csrf')
        return {
          ok: true,
          status: 200,
          redirected: true,
          url: 'http://localhost/libraries',
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async () => JSON.stringify({}),
          json: async () => ({}),
        }
      }
      if (href.includes('/api/get_libraries')) {
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => [{ uuid: 'lib-switch-1', name: 'Nintendo Switch' }],
        }
      }
      if (href.includes(LIBRARY_SCAN_URL)) {
        const body = JSON.parse(opts.body)
        expect(body.library_uuid).toBe('lib-switch-1')
        expect(body.folder).toBe(CANDIDATES[0].path)
        expect(body.scan_mode).toBe('folders')
        expect(body.queue_policy).toBe('queue')
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => ({ status: 'queued', job_id: 'job-1' }),
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

    render(<ImportLeafLibraries />)

    setPasteValue(
      /json text/i,
      '[{"path":"/storage/games/Switch","platform":"SWITCH","suggested_name":"Nintendo Switch","scan_mode":"folders","scan_depth":1}]',
    )
    await user.click(screen.getByRole('button', { name: /^preview$/i }))

    expect(await screen.findByText('Nintendo Switch')).toBeInTheDocument()
    expect(screen.getByText('PlayStation (PSX)')).toBeInTheDocument()
    expect(screen.getByText(/family_parent_rejected/i)).toBeInTheDocument()
    expect(screen.getByText(/Nothing is created until you confirm/i)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /row errors/i })).toBeInTheDocument()

    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes(LIBRARY_ADD_URL))).toBe(false)

    await user.click(screen.getByRole('checkbox', { name: /select nintendo switch/i }))
    await user.click(screen.getByRole('button', { name: /confirm create \(1\)/i }))
    // The house dialog, not window.confirm (UID-042): the named button in it
    // is what actually commits, so the test has to press it.
    await user.click(await screen.findByRole('button', { name: /^create library$/i }))

    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).includes(LIBRARY_ADD_URL))).toBe(true)
    })
    await waitFor(() => {
      expect(fetchMock.mock.calls.some((c) => String(c[0]).includes(LIBRARY_SCAN_URL))).toBe(true)
    })
    expect(await screen.findByText(/1 created/i)).toBeInTheDocument()
  })

  test('soft-degrades when import preview API returns 404', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (): Promise<any> => ({
        ok: false,
        status: 404,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({}),
      })),
    )

    render(<ImportLeafLibraries />)
    setPasteValue(/json text/i, '[{"path":"/x","platform":"NES"}]')
    await user.click(screen.getByRole('button', { name: /^preview$/i }))

    expect(await screen.findByText(/not available on this build yet/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /confirm create/i })).not.toBeInTheDocument()
  })

  test('refuses payload when server claims auto_create true', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (): Promise<any> => ({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({
          status: 'ok',
          auto_create: true,
          candidates: CANDIDATES,
          errors: [],
          count: 2,
          error_count: 0,
        }),
      })),
    )

    render(<ImportLeafLibraries />)
    setPasteValue(/json text/i, '[{"path":"/x","platform":"NES"}]')
    await user.click(screen.getByRole('button', { name: /^preview$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/auto_create/i)
    expect(screen.queryByRole('button', { name: /confirm create/i })).not.toBeInTheDocument()
  })

  test('CSV paste posts form csv field then enables confirm', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn(async (url, opts) => {
      if (String(url).includes(IMPORT_LEAF_PREVIEW_URL)) {
        expect(opts.body).toBeInstanceOf(FormData)
        expect(opts.body.get('csv')).toContain('SWITCH')
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => ({
            status: 'ok',
            auto_create: false,
            count: 1,
            error_count: 0,
            candidates: [CANDIDATES[0]],
            errors: [],
          }),
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

    render(<ImportLeafLibraries />)
    await user.click(screen.getByRole('radio', { name: /paste csv/i }))
    setPasteValue(/csv text/i, 'path,platform\n/storage/games/Switch,SWITCH\n')
    await user.click(screen.getByRole('button', { name: /^preview$/i }))

    expect(await screen.findByText('Nintendo Switch')).toBeInTheDocument()
    await user.click(screen.getByLabelText(/select all/i))
    expect(screen.getByRole('button', { name: /confirm create \(1\)/i })).toBeEnabled()
  })

  test('shows errors separate when only rejected rows', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (): Promise<any> => ({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({
          status: 'ok',
          auto_create: false,
          count: 0,
          error_count: 1,
          candidates: [],
          errors: ROW_ERRORS,
        }),
      })),
    )

    render(<ImportLeafLibraries />)
    setPasteValue(/json text/i, '[{"path":"/storage/games/NINTENDO","platform":"SWITCH"}]')
    await user.click(screen.getByRole('button', { name: /^preview$/i }))

    expect(await screen.findByRole('heading', { name: /row errors/i })).toBeInTheDocument()
    expect(screen.getByText(/family_parent_rejected/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /confirm create/i })).not.toBeInTheDocument()
  })

  test('confirm cancelled does not create', async () => {
    const user = userEvent.setup()

    const fetchMock = vi.fn(async (url) => {
      if (String(url).includes(IMPORT_LEAF_PREVIEW_URL)) {
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async function () {
            return JSON.stringify(await this.json())
          },
          json: async () => ({
            status: 'ok',
            auto_create: false,
            count: 1,
            error_count: 0,
            candidates: [CANDIDATES[0]],
            errors: [],
          }),
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

    render(<ImportLeafLibraries />)
    setPasteValue(/json text/i, '[{"path":"/storage/games/Switch","platform":"SWITCH"}]')
    await user.click(screen.getByRole('button', { name: /^preview$/i }))
    await screen.findByText('Nintendo Switch')
    await user.click(screen.getByRole('checkbox', { name: /select nintendo switch/i }))
    await user.click(screen.getByRole('button', { name: /confirm create \(1\)/i }))
    await user.click(await screen.findByRole('button', { name: /^cancel$/i }))

    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes(LIBRARY_ADD_URL))).toBe(false)
  })
})
