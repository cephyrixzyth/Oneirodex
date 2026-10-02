import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { ProposeLeafLibraries } from './ProposeLeafLibraries'
import { LIBRARY_ADD_URL, LIBRARY_SCAN_URL, PROPOSE_LEAF_URL } from '../api/proposeLeafLibrariesApi'

const CANDIDATES = [
  {
    path: '/storage/games/_console-gaming/NINTENDO/NES/ROMs',
    suggested_name: 'NES ROMs',
    platform: 'NES',
    scan_mode: 'files',
    scan_depth: 1,
    reason: 'dump leaf (ROMs); flat rom files',
  },
  {
    path: '/storage/games/_console-gaming/Sony/PlayStation/ROMs',
    suggested_name: 'PlayStation (PSX)',
    platform: 'PSX',
    scan_mode: 'folders',
    scan_depth: 1,
    reason: 'nested dump under platform',
  },
]

describe('ProposeLeafLibraries', () => {
  beforeEach(() => {
    document.head.innerHTML = '<meta name="csrf-token" content="test-csrf">'
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  test('propose → multi-select → confirm posts create then scan (never on propose)', async () => {
    const user = userEvent.setup()

    const fetchMock = vi.fn(async (url, opts) => {
      const href = String(url)
      if (href.includes(PROPOSE_LEAF_URL)) {
        expect(opts?.method).toBe('POST')
        const body = JSON.parse(opts.body)
        expect(body.root).toBe('/storage/games/_console-gaming')
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async () => JSON.stringify({}),
          json: async () => ({
            status: 'ok',
            root: '/storage/games/_console-gaming',
            auto_create: false,
            count: 2,
            candidates: CANDIDATES,
          }),
        }
      }
      if (href.includes(LIBRARY_ADD_URL)) {
        expect(opts?.method).toBe('POST')
        const form = opts.body
        expect(form.get('name')).toBe('NES ROMs')
        expect(form.get('platform')).toBe('NES')
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

          text: async () => JSON.stringify({}),
          json: async () => [{ uuid: 'lib-nes-1', name: 'NES ROMs' }],
        }
      }
      if (href.includes(LIBRARY_SCAN_URL)) {
        const body = JSON.parse(opts.body)
        expect(body.library_uuid).toBe('lib-nes-1')
        expect(body.folder).toBe(CANDIDATES[0].path)
        expect(body.scan_mode).toBe('files')
        expect(body.queue_policy).toBe('queue')
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async () => JSON.stringify({}),
          json: async () => ({ status: 'queued', job_id: 'job-1' }),
        }
      }
      return {
        ok: false,
        status: 404,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async () => JSON.stringify({}),
        json: async () => ({}),
      }
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ProposeLeafLibraries />)

    await user.type(screen.getByLabelText(/root path/i), '/storage/games/_console-gaming')
    await user.click(screen.getByRole('button', { name: /^propose$/i }))

    expect(await screen.findByText('NES ROMs')).toBeInTheDocument()
    expect(screen.getByText('PlayStation (PSX)')).toBeInTheDocument()
    expect(screen.getByText(/Nothing is created until you confirm/i)).toBeInTheDocument()

    // Propose only — no library create yet
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes(LIBRARY_ADD_URL))).toBe(false)

    const nesCheckbox = screen.getByRole('checkbox', { name: /select nes roms/i })
    await user.click(nesCheckbox)
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

  test('soft-degrades when propose API returns 404', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (): Promise<any> => ({
        ok: false,
        status: 404,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async () => JSON.stringify({}),
        json: async () => ({}),
      })),
    )

    render(<ProposeLeafLibraries />)
    await user.type(screen.getByLabelText(/root path/i), '/storage/games')
    await user.click(screen.getByRole('button', { name: /^propose$/i }))

    expect(await screen.findByText(/not available on this build yet/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /confirm create/i })).not.toBeInTheDocument()
  })

  test('honest empty state when API returns zero candidates', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (): Promise<any> => ({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async () => JSON.stringify({}),
        json: async () => ({
          status: 'ok',
          root: '/storage/games/_console-gaming',
          auto_create: false,
          count: 0,
          candidates: [],
        }),
      })),
    )

    render(<ProposeLeafLibraries />)
    await user.type(screen.getByLabelText(/root path/i), '/storage/games/_console-gaming')
    await user.click(screen.getByRole('button', { name: /^propose$/i }))

    expect(await screen.findByText(/No leaf candidates under this root/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /confirm create/i })).not.toBeInTheDocument()
  })

  test('select all enables confirm for every candidate', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url) => {
        if (String(url).includes(PROPOSE_LEAF_URL)) {
          return {
            ok: true,
            status: 200,
            headers: new Headers({ 'content-type': 'application/json' }),

            text: async () => JSON.stringify({}),
            json: async () => ({
              status: 'ok',
              root: '/r',
              auto_create: false,
              count: 2,
              candidates: CANDIDATES,
            }),
          }
        }
        return {
          ok: false,
          status: 404,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async () => JSON.stringify({}),
          json: async () => ({}),
        }
      }),
    )

    render(<ProposeLeafLibraries />)
    await user.type(screen.getByLabelText(/root path/i), '/r')
    await user.click(screen.getByRole('button', { name: /^propose$/i }))
    await screen.findByText('NES ROMs')

    await user.click(screen.getByLabelText(/select all/i))
    expect(screen.getByRole('button', { name: /confirm create \(2\)/i })).toBeEnabled()
  })

  test('confirm cancelled does not create', async () => {
    const user = userEvent.setup()

    const fetchMock = vi.fn(async (url) => {
      if (String(url).includes(PROPOSE_LEAF_URL)) {
        return {
          ok: true,
          status: 200,
          headers: new Headers({ 'content-type': 'application/json' }),

          text: async () => JSON.stringify({}),
          json: async () => ({
            status: 'ok',
            root: '/r',
            auto_create: false,
            count: 1,
            candidates: [CANDIDATES[0]],
          }),
        }
      }
      return {
        ok: false,
        status: 404,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async () => JSON.stringify({}),
        json: async () => ({}),
      }
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ProposeLeafLibraries />)
    await user.type(screen.getByLabelText(/root path/i), '/r')
    await user.click(screen.getByRole('button', { name: /^propose$/i }))
    await screen.findByText('NES ROMs')
    await user.click(screen.getByRole('checkbox', { name: /select nes roms/i }))
    await user.click(screen.getByRole('button', { name: /confirm create \(1\)/i }))
    await user.click(await screen.findByRole('button', { name: /^cancel$/i }))

    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes(LIBRARY_ADD_URL))).toBe(false)
  })

  test('shows API error message honestly', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(async (): Promise<any> => ({
        ok: false,
        status: 403,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async () => JSON.stringify({}),
        json: async () => ({ status: 'error', message: 'Unsafe path' }),
      })),
    )

    render(<ProposeLeafLibraries />)
    await user.type(screen.getByLabelText(/root path/i), '/etc')
    await user.click(screen.getByRole('button', { name: /^propose$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Unsafe path')
  })
})
