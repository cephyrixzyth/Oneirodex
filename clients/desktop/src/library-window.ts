import { WebviewWindow } from '@tauri-apps/api/webviewWindow'

import { isTauriRuntime } from './config-store.js'
import { joinUrl } from './paths.js'

const LIBRARY_LABEL = 'full-library'
let lastLibraryUrl = ''

export function buildFullLibraryUrl(baseUrl: string): string {
  const base = baseUrl.trim()
  return base ? joinUrl(base, '/library') : ''
}

export async function openFullLibraryWindow(
  baseUrl: string,
): Promise<'opened' | 'focused' | 'browser'> {
  const url = buildFullLibraryUrl(baseUrl)
  if (!url) throw new Error('Set Server URL first.')

  if (!isTauriRuntime()) {
    window.open(url, 'od-full-library', 'width=1280,height=800')
    return 'browser'
  }

  const existing = await WebviewWindow.getByLabel(LIBRARY_LABEL)
  if (existing) {
    if (lastLibraryUrl && lastLibraryUrl !== url) {
      try {
        await existing.close()
      } catch {
        // Recreate below; a stale window must not keep its previous server.
      }
    } else {
      await existing.show()
      await existing.setFocus()
      lastLibraryUrl = url
      return 'focused'
    }
  }

  const webview = new WebviewWindow(LIBRARY_LABEL, {
    url,
    title: 'Oneirodex Library',
    width: 1280,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    resizable: true,
    focus: true,
  })
  await new Promise<void>((resolve, reject) => {
    webview.once('tauri://created', () => resolve())
    webview.once('tauri://error', (event) => {
      const message =
        typeof event === 'string'
          ? event
          : event && typeof event === 'object' && 'payload' in event
            ? String((event as { payload?: unknown }).payload ?? 'window creation failed')
            : 'window creation failed'
      reject(new Error(message))
    })
  })
  lastLibraryUrl = url
  return 'opened'
}

export function resetFullLibraryWindowForTests(): void {
  lastLibraryUrl = ''
}
