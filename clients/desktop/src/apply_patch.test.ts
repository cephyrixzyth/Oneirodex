import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))

vi.mock('./config-store.js', () => ({
  isTauriRuntime: () => true,
}))

import { invoke } from '@tauri-apps/api/core'
import {
  buildFlipsApplyArgs,
  isPatchFilename,
  patchedOutputName,
  MAX_PATCH_DOWNLOAD_BYTES,
  readBoundedPatchResponse,
  resolvePatchStageDir,
  safePatchFilename,
  stagePatchFile,
} from './apply_patch.js'

describe('apply_patch helpers', () => {
  beforeEach(() => {
    vi.mocked(invoke).mockReset()
  })

  it('sanitizes patch filenames', () => {
    expect(safePatchFilename('../evil.bps')).toBe('evil.bps')
    expect(safePatchFilename('')).toBe('patch.bps')
  })

  it('resolves stage dir under patches root', () => {
    expect(resolvePatchStageDir('/appdata/patches/', 'abc-123')).toBe('/appdata/patches/abc-123')
  })

  it('builds flips CLI args', () => {
    expect(
      buildFlipsApplyArgs({
        flipsPath: 'C:\\Tools\\flips.exe',
        patchPath: '/p/a.bps',
        romPath: '/p/game.sfc',
        outputPath: '/p/out.sfc',
      }),
    ).toEqual(['C:\\Tools\\flips.exe', '--apply', '/p/a.bps', '/p/game.sfc', '/p/out.sfc'])
  })

  it('detects patch extensions', () => {
    expect(isPatchFilename('x.bps')).toBe(true)
    expect(isPatchFilename('x.IPS')).toBe(true)
    expect(isPatchFilename('x.txt')).toBe(false)
  })

  it('names patched output', () => {
    expect(patchedOutputName('game.sfc', 'en.bps')).toBe('game.patched-bps.sfc')
  })

  it('stagePatchFile writes under app_data/patches via write_file_bytes', async () => {
    vi.mocked(invoke).mockImplementation(async (command: string) => {
      if (command === 'get_app_subdir') {
        return '/appdata/patches'
      }
      return undefined
    })
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        url: 'https://gt.example/api/downloads/games/game-42',
        json: async () => ({ ok: true, stream_url: '/download_zip/80' }),
      })
      .mockResolvedValueOnce(
        new Response(new TextEncoder().encode('BPS1'), { status: 200 }),
      ) as unknown as typeof fetch

    const result = await stagePatchFile({
      gameUuid: 'game-42',
      patchUuid: 'patch-9',
      filename: 'en.bps',
      apiBase: 'https://gt.example',
      fetchImpl,
    })

    expect(result).toEqual({ ok: true, path: '/appdata/patches/game-42/en.bps' })
    expect(fetchImpl).toHaveBeenNthCalledWith(
      1,
      'https://gt.example/api/downloads/games/game-42',
      expect.objectContaining({
        method: 'POST',
        credentials: 'omit',
        redirect: 'error',
        body: JSON.stringify({ kind: 'extra', version_uuid: 'patch-9' }),
      }),
    )
    expect(fetchImpl).toHaveBeenNthCalledWith(
      2,
      'https://gt.example/download_zip/80',
      expect.objectContaining({ credentials: 'omit', redirect: 'error' }),
    )
    expect(invoke).toHaveBeenCalledWith('write_file_bytes', {
      path: '/appdata/patches/game-42/en.bps',
      bytes: expect.any(Array),
    })
  })

  it('rejects an oversized declared patch response before reading or writing it', async () => {
    vi.mocked(invoke).mockImplementation(async () => undefined)
    const fetchImpl = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        url: 'https://gt.example/api/downloads/games/game-42',
        json: async () => ({ ok: true, stream_url: '/download_zip/80' }),
      })
      .mockResolvedValueOnce(
        new Response(new Uint8Array([1]), {
          status: 200,
          headers: { 'content-length': String(MAX_PATCH_DOWNLOAD_BYTES + 1) },
        }),
      ) as unknown as typeof fetch

    const result = await stagePatchFile({
      gameUuid: 'game-42',
      patchUuid: 'patch-9',
      apiBase: 'https://gt.example',
      fetchImpl,
    })

    expect(result).toEqual({
      ok: false,
      error: 'Patch download exceeds the 256 MiB limit',
    })
    expect(invoke).not.toHaveBeenCalledWith('write_file_bytes', expect.anything())
  })

  it('does not let a non-finite helper limit disable the production ceiling', async () => {
    const response = new Response(new Uint8Array([1]), {
      status: 200,
      headers: { 'content-length': String(MAX_PATCH_DOWNLOAD_BYTES + 1) },
    })

    await expect(
      readBoundedPatchResponse(response, Number.POSITIVE_INFINITY),
    ).rejects.toThrow('Patch download exceeds the 256 MiB limit')
  })

  it('enforces the same byte ceiling when the stream exceeds its declared size', async () => {
    const response = new Response(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new Uint8Array([1, 2, 3]))
          controller.enqueue(new Uint8Array([4, 5, 6]))
          controller.close()
        },
      }),
      { status: 200, headers: { 'content-length': '3' } },
    )

    await expect(readBoundedPatchResponse(response, 5)).rejects.toThrow(
      'Patch download exceeds',
    )
  })

  it('preserves a normal patch response under the byte ceiling', async () => {
    const response = new Response(new TextEncoder().encode('BPS1'), { status: 200 })

    await expect(readBoundedPatchResponse(response, 4)).resolves.toEqual(
      new Uint8Array([66, 80, 83, 49]),
    )
  })
})
