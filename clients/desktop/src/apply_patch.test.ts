import { describe, expect, it, vi, beforeEach } from 'vitest'

vi.mock('@tauri-apps/api/core', () => ({
  invoke: vi.fn(),
}))

vi.mock('./config-store.js', () => ({
  isTauriRuntime: () => true,
}))

import { invoke } from '@tauri-apps/api/core'
import {
  MAX_PATCH_DOWNLOAD_BYTES,
  streamBoundedPatchResponse,
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
    expect(safePatchFilename('')).toBe('patch')
  })

  it('resolves stage dir under patches root', () => {
    expect(resolvePatchStageDir('/appdata/patches/', 'abc-123')).toBe('/appdata/patches/abc-123')
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

    expect(result).toEqual({
      ok: true,
      path: expect.stringMatching(/^\/appdata\/patches\/\.staging\/game-42\/[^/]+-en\.bps$/),
    })
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
      path: expect.stringMatching(/^\/appdata\/patches\/\.staging\/game-42\/[^/]+-en\.bps$/),
      bytes: new Uint8Array([66, 80, 83, 49]),
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
      streamBoundedPatchResponse(response, vi.fn(), Number.POSITIVE_INFINITY),
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

    await expect(streamBoundedPatchResponse(response, vi.fn(), 5)).rejects.toThrow(
      'Patch download exceeds',
    )
  })

  it('preserves a normal patch response under the byte ceiling', async () => {
    const response = new Response(new TextEncoder().encode('BPS1'), { status: 200 })

    const sink = vi.fn()
    await expect(streamBoundedPatchResponse(response, sink, 4)).resolves.toBe(4)
    expect(sink).toHaveBeenCalledWith(new Uint8Array([66, 80, 83, 49]))
  })
})
