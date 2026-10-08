import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import { EmulatorFirmwarePanel, coreLabel, formatBytes } from './EmulatorFirmwarePanel'

const SUMMARY = {
  files: [{ name: 'scph5501.bin', size: 524288 }],
  cores: [
    {
      core: 'mednafen_psx_hw',
      required: ['scph5500.bin', 'scph5501.bin'],
      present: ['scph5501.bin'],
      ready: true,
    },
    { core: 'yabause', required: ['saturn_bios.bin'], present: [], ready: false },
  ],
}

function mockGet(payload = SUMMARY) {
  globalThis.fetch = vi.fn(async (): Promise<any> => ({
    ok: true,
    status: 200,
    headers: new Headers({ 'content-type': 'application/json' }),

    text: async function () {
      return JSON.stringify(await this.json())
    },
    json: async () => payload,
  })) as unknown as typeof globalThis.fetch
}

afterEach(() => {
  vi.restoreAllMocks()
})

test('formatBytes is honest about unknown sizes', () => {
  expect(formatBytes(512)).toBe('512 B')
  expect(formatBytes(524288)).toBe('512.0 KB')
  expect(formatBytes(2 * 1024 * 1024)).toBe('2.0 MB')
  expect(formatBytes(null)).toBe('n/a')
  expect(formatBytes(-1)).toBe('n/a')
})

test('coreLabel maps libretro ids to human names and passes unknowns through', () => {
  expect(coreLabel('mednafen_psx_hw')).toBe('PlayStation')
  expect(coreLabel('some_new_core')).toBe('some_new_core')
})

test('renders coverage, cores and files', async () => {
  mockGet()
  render(<EmulatorFirmwarePanel />)

  expect(await screen.findByText('PlayStation')).toBeInTheDocument()
  expect(screen.getByText('Saturn')).toBeInTheDocument()
  expect(screen.getByText('missing system files')).toBeInTheDocument()
  expect(screen.getByText('scph5501.bin')).toBeInTheDocument()
  expect(screen.getByLabelText('Firmware coverage')).toBeInTheDocument()
})

test('never offers to download BIOS — product stance', async () => {
  mockGet()
  render(<EmulatorFirmwarePanel />)
  await screen.findByText('PlayStation')

  expect(screen.queryByRole('button', { name: /download/i })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /download/i })).not.toBeInTheDocument()
  expect(screen.getByText(/never downloads BIOS for you/i)).toBeInTheDocument()
})

test('empty volume states the play consequence rather than just "none"', async () => {
  mockGet({ files: [], cores: SUMMARY.cores })
  render(<EmulatorFirmwarePanel />)

  expect(
    await screen.findByText(/Cores that need it will stay unavailable for browser play/i),
  ).toBeInTheDocument()
})

test('surfaces the backend rejection message on a failed upload', async () => {
  mockGet()
  render(<EmulatorFirmwarePanel />)
  await screen.findByText('PlayStation')

  globalThis.fetch = vi.fn(async (): Promise<any> => ({
    ok: false,
    status: 422,
    headers: new Headers({ 'content-type': 'application/json' }),

    text: async function () {
      return JSON.stringify(await this.json())
    },
    json: async () => ({
      ok: false,
      error: 'Unsupported firmware file type ".exe". Allowed: .bin, .rom',
      error_code: 'unprocessable',
    }),
  })) as unknown as typeof globalThis.fetch

  const file = new File(['x'], 'bad.exe', { type: 'application/octet-stream' })
  await userEvent.upload(screen.getByLabelText('Firmware file'), file)

  expect(await screen.findByRole('alert')).toHaveTextContent(
    'Unsupported firmware file type ".exe"',
  )
})

test('upload carries the CSRF token', async () => {
  // Without it, CSRFProtect rejects the POST with 400 before the route sees the
  // file, and firmware upload simply does not work. This is the regression that
  // made it look broken.
  document.head.innerHTML = '<meta name="csrf-token" content="test-csrf">'
  mockGet()
  render(<EmulatorFirmwarePanel />)
  await screen.findByText('PlayStation')

  const postFetch = vi.fn(async (): Promise<any> => ({
    ok: true,
    status: 201,
    headers: new Headers({ 'content-type': 'application/json' }),

    text: async function () {
      return JSON.stringify(await this.json())
    },
    json: async () => ({ ok: true, data: { name: 'scph5500.bin', size: 524288 } }),
  }))
  globalThis.fetch = postFetch as unknown as typeof globalThis.fetch

  const file = new File(['x'], 'scph5500.bin', { type: 'application/octet-stream' })
  await userEvent.upload(screen.getByLabelText('Firmware file'), file)

  await waitFor(() => {
    const call = postFetch.mock.calls.find((c: any[]) => c[1]?.method === 'POST') as
      any[] | undefined
    expect(call).toBeTruthy()
    expect(call![1].headers['X-CSRFToken']).toBe('test-csrf')
    expect(call![1].body.get('csrf_token')).toBe('test-csrf')
    expect(call![1].body.get('file')).toBe(file)
  })
})

test('read failure offers a retry rather than an empty page', async () => {
  globalThis.fetch = vi.fn(async (): Promise<any> => ({
    ok: false,
    status: 500,
    headers: new Headers({ 'content-type': 'application/json' }),

    text: async function () {
      return JSON.stringify(await this.json())
    },
    json: async () => ({ error: 'Volume not mounted' }),
  })) as unknown as typeof globalThis.fetch
  render(<EmulatorFirmwarePanel />)

  expect(await screen.findByRole('alert')).toHaveTextContent('Volume not mounted')

  mockGet()
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await waitFor(() => expect(screen.getByText('PlayStation')).toBeInTheDocument())
})

const SATURN_A = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
const SATURN_B = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'

const SCAN_PLAN = {
  matches: [
    {
      name: 'saturn_bios.bin',
      already: false,
      chosen: SATURN_A,
      note: '2 candidates, 2 differ — default is the 1-copy majority',
      systems: [{ label: 'Saturn', platform: 'SATURN', hard: true }],
      versions: [
        {
          digest: SATURN_A,
          size: 512,
          count: 1,
          paths: ['pack-a/saturn_bios.bin'],
        },
        {
          digest: SATURN_B,
          size: 640,
          count: 1,
          paths: ['pack-b/saturn_bios.bin'],
        },
      ],
    },
  ],
  missing: [{ name: 'scph5501.bin', blocking: true }],
  conflicts: [{ name: 'saturn_bios.bin', versions: [{ digest: SATURN_A }, { digest: SATURN_B }] }],
  missing_markdown: '# Firmware still needed\n\n- **PlayStation** — `scph5501.bin`\n',
  copy_count: 1,
  already_count: 0,
  conflict_count: 1,
  copied_count: 1,
}

function mockApi({
  get = SUMMARY,
  scan = SCAN_PLAN,
  install = SCAN_PLAN,
}: { get?: any; scan?: any; install?: any } = {}) {
  globalThis.fetch = vi.fn(async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    const path = String(url)
    if (method === 'POST' && path.includes('/scan')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({ ok: true, ...scan }),
      }
    }
    if (method === 'POST' && path.includes('/install')) {
      return {
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({ ok: true, ...install }),
      }
    }
    if (method === 'POST') {
      return {
        ok: true,
        status: 201,
        headers: new Headers({ 'content-type': 'application/json' }),

        text: async function () {
          return JSON.stringify(await this.json())
        },
        json: async () => ({ ok: true, name: 'scph5500.bin', size: 524288 }),
      }
    }
    return {
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),

      text: async function () {
        return JSON.stringify(await this.json())
      },
      json: async () => get,
    }
  }) as unknown as typeof globalThis.fetch
}

test('offers scan, install, and a copyable missing report — never a download', async () => {
  mockApi({ get: { ...SUMMARY, missing_markdown: SCAN_PLAN.missing_markdown } })
  render(<EmulatorFirmwarePanel />)
  await screen.findByText('PlayStation')

  expect(screen.getByRole('button', { name: 'Scan collection' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Install matching firmware' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Show missing report' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /download/i })).not.toBeInTheDocument()
})

test('scan posts the folder and opens markdown the operator can copy', async () => {
  const writeText = vi.fn(async () => {})
  Object.assign(navigator, { clipboard: { writeText } })
  document.head.innerHTML = '<meta name="csrf-token" content="test-csrf">'
  mockApi()
  render(<EmulatorFirmwarePanel />)
  await screen.findByText('PlayStation')

  await userEvent.type(screen.getByLabelText('Firmware collection folder'), 'E:\\_bios')
  await userEvent.click(screen.getByRole('button', { name: 'Scan collection' }))

  expect(await screen.findByRole('dialog', { name: 'Missing firmware' })).toBeInTheDocument()
  expect(screen.getByLabelText('Missing firmware report (markdown)')).toHaveValue(
    SCAN_PLAN.missing_markdown,
  )
  expect(screen.getByText('Which dump for saturn_bios.bin')).toBeInTheDocument()
  expect(screen.getByLabelText(/pack-a\/saturn_bios.bin/)).toBeInTheDocument()

  const scanCall = vi
    .mocked(globalThis.fetch)
    .mock.calls.find(([url, init]: any) => String(url).includes('/scan') && init?.method === 'POST')
  expect(scanCall).toBeTruthy()
  expect(JSON.parse((scanCall as any[])[1].body)).toEqual({ source: 'E:\\_bios' })
  // The browser transport (PR-4c) builds a `Headers` instance rather than a
  // plain object, so bracket access no longer reads it — use `.get()`.
  expect(new Headers((scanCall as any[])[1].headers).get('X-CSRFToken')).toBe('test-csrf')

  await userEvent.click(screen.getByRole('button', { name: 'Copy markdown' }))
  await waitFor(() => {
    expect(writeText).toHaveBeenCalledWith(SCAN_PLAN.missing_markdown)
  })
})

test('install sends the dump the operator picked', async () => {
  document.head.innerHTML = '<meta name="csrf-token" content="test-csrf">'
  mockApi()
  render(<EmulatorFirmwarePanel />)
  await screen.findByText('PlayStation')
  await userEvent.type(screen.getByLabelText('Firmware collection folder'), '/bios')
  await userEvent.click(screen.getByRole('button', { name: 'Scan collection' }))
  await screen.findByRole('dialog', { name: 'Missing firmware' })
  await userEvent.click(screen.getByRole('button', { name: 'Close' }))

  await userEvent.click(screen.getByLabelText(/pack-b\/saturn_bios.bin/))
  await userEvent.click(screen.getByRole('button', { name: 'Install matching firmware' }))

  await waitFor(() => {
    const installCall = vi
      .mocked(globalThis.fetch)
      .mock.calls.find(
        ([url, init]: any) => String(url).includes('/install') && init?.method === 'POST',
      )
    expect(installCall).toBeTruthy()
    expect(JSON.parse((installCall as any[])[1].body)).toEqual({
      source: '/bios',
      selections: { 'saturn_bios.bin': SATURN_B },
      skipped: [],
      overwrite: false,
    })
  })
})

test('folder upload sends only firmware names required by configured cores', async () => {
  mockApi({ get: { ...SUMMARY, files: [] } })
  render(<EmulatorFirmwarePanel />)
  await screen.findByText('PlayStation')

  expect(screen.getByLabelText('Firmware folder')).toHaveAttribute('webkitdirectory', 'true')
  const firmware = new File(['saturn'], 'saturn_bios.bin', {
    type: 'application/octet-stream',
  })
  Object.defineProperty(firmware, 'webkitRelativePath', { value: 'collection/saturn_bios.bin' })
  const unrelated = new File(['data'], 'unrelated.iso', { type: 'application/octet-stream' })
  await userEvent.upload(screen.getByLabelText('Firmware folder'), [firmware, unrelated])

  expect(await screen.findAllByText(/Uploaded 1 matching file/)).not.toHaveLength(0)
  const uploadCall = vi
    .mocked(globalThis.fetch)
    .mock.calls.find(
      ([url, init]: any) => String(url) === '/api/emulator-bios' && init?.method === 'POST',
    )
  expect(uploadCall).toBeTruthy()
  const body = (uploadCall as any[])[1].body as FormData
  expect((body.get('file') as File).name).toBe('saturn_bios.bin')
})

test('folder upload refuses ambiguous duplicate firmware filenames', async () => {
  mockApi({ get: { ...SUMMARY, files: [] } })
  render(<EmulatorFirmwarePanel />)
  await screen.findByText('PlayStation')

  const first = new File(['region-a'], 'saturn_bios.bin', { type: 'application/octet-stream' })
  const second = new File(['region-b'], 'saturn_bios.bin', { type: 'application/octet-stream' })
  await userEvent.upload(screen.getByLabelText('Firmware folder'), [first, second])

  expect(await screen.findByRole('alert')).toHaveTextContent('Use the collection scanner')
  expect(
    vi.mocked(globalThis.fetch).mock.calls.some(
      ([url, init]: any) => String(url) === '/api/emulator-bios' && init?.method === 'POST',
    ),
  ).toBe(false)
})
