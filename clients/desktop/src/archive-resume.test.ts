import { expect, it, vi } from 'vitest'
import { createHash, webcrypto } from 'node:crypto'
import { invoke } from '@tauri-apps/api/core'
import { createAuthStore } from './auth'
import { streamDownloadToFile } from './download'
vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))
vi.mock('./config-store.js', () => ({ isTauriRuntime: () => true }))

it.each([
  'resume',
  'changed',
  'ignored-range',
  'wrong-range',
  'disk-full',
  'account-switch',
  'no-validator',
] as const)('stages and verifies an interrupted download (%s)', async (scenario) => {
  const disk = new Map<string, Buffer>()
  const finalPath = '/downloads/game.zip'
  const previous = Buffer.from('previous archive')
  disk.set(finalPath, previous)
  const receipt = new Map<string, string>()
  vi.stubGlobal('crypto', webcrypto)
  vi.stubGlobal('navigator', {
    locks: { request: async (_name: string, fn: () => Promise<void>) => fn() },
  })
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => receipt.get(k) || null,
    setItem: (k: string, v: string) => receipt.set(k, v),
    removeItem: (k: string) => receipt.delete(k),
  })
  const complete = Buffer.from([80, 75, 3, 4, 7, 8, 9, 10])
  const etag = '"sha256-' + createHash('sha256').update(complete).digest('hex') + '"'
  const auth = createAuthStore({ baseUrl: 'https://example.com', token: 'test-token' })
  vi.mocked(invoke).mockImplementation(async (command, args) => {
    const data = args as { path: string; bytes: Uint8Array; scope: string }
    if (command === 'archive_checkpoint') {
      const file = disk.get(data.path) || Buffer.alloc(0)
      return { size: file.length, sha256: createHash('sha256').update(file).digest('hex') }
    }
    if (command === 'write_file_bytes') disk.set(data.path, Buffer.from(data.bytes))
    if (command === 'append_file_bytes') {
      if (scenario === 'disk-full' && attempts === 2) throw Error('disk full')
      disk.set(data.path, Buffer.concat([disk.get(data.path)!, data.bytes]))
    }
    if (command === 'remove_path') disk.delete(data.path)
    if (command === 'publish_archive_checkpoint') {
      const staged = data.path + '.' + data.scope + '.part'
      if (!disk.has(staged)) throw Error('no staged archive')
      disk.set(data.path, disk.get(staged)!)
      disk.delete(staged)
    }
  })
  const changed = Buffer.from([80, 75, 3, 4, 9, 9, 9, 9])
  const changedTag = '"sha256-' + createHash('sha256').update(changed).digest('hex') + '"'
  let attempts = 0
  const fetchImpl = vi.fn(async (_url: unknown, options?: RequestInit) => {
    const headers = new Headers(options?.headers)
    expect(headers.get('X-Oneirodex-Resume')).toBe('1')
    if (attempts++ === 0) {
      let sent = false
      return new Response(
        new ReadableStream({
          pull(controller) {
            if (sent) {
              controller.error(Error('connection interrupted'))
              return
            }
            sent = true
            controller.enqueue(complete.subarray(0, 4))
          },
        }),
        { headers: { 'Content-Length': '8', ETag: etag } },
      )
    }
    if (scenario === 'account-switch' || (scenario === 'wrong-range' && attempts === 3)) {
      expect(headers.get('Range')).toBe(null)
      return new Response(complete, { headers: { 'Content-Length': '8', ETag: etag } })
    }
    expect(headers.get('Range')).toBe('bytes=4-')
    expect(headers.get('If-Range')).toBe(etag)
    if (scenario === 'changed')
      return new Response(changed, { headers: { 'Content-Length': '8', ETag: changedTag } })
    if (scenario === 'ignored-range')
      return new Response(complete, { headers: { 'Content-Length': '8', ETag: etag } })
    if (scenario === 'no-validator')
      return new Response(complete, { headers: { 'Content-Length': '8' } })
    if (scenario === 'wrong-range')
      return new Response(complete.subarray(4), {
        status: 206,
        headers: { 'Content-Length': '4', 'Content-Range': 'bytes 3-6/8', ETag: etag },
      })
    return new Response(complete.subarray(4), {
      status: 206,
      headers: { 'Content-Length': '4', 'Content-Range': 'bytes 4-7/8', ETag: etag },
    })
  })
  try {
    const options = {
      fetchImpl: fetchImpl as typeof fetch,
      resumeIdentity: 'game-A',
      archiveRepresentation: 'companion_zip' as const,
    }
    await expect(
      streamDownloadToFile(auth, '/download_zip/1', '/downloads/game.zip', options),
    ).rejects.toThrow()
    expect(disk.get(finalPath)).toEqual(previous)
    const secondAuth =
      scenario === 'account-switch'
        ? createAuthStore({ baseUrl: 'https://example.com', token: 'second-account' })
        : auth
    const retry = () => streamDownloadToFile(secondAuth, '/download_zip/2', finalPath, options)
    if (scenario === 'disk-full' || scenario === 'wrong-range') {
      await expect(retry()).rejects.toThrow()
      expect(disk.get(finalPath)).toEqual(previous)
    }
    await retry()
    expect(disk.get(finalPath)).toEqual(scenario === 'changed' ? changed : complete)
    expect(receipt.size).toBe(scenario === 'account-switch' ? 1 : 0)
  } finally {
    vi.unstubAllGlobals()
  }
})
