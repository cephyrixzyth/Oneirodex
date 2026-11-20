import { WebviewWindow } from '@tauri-apps/api/webviewWindow'

import { isTauriRuntime } from './config-store.js'
import { joinUrl } from './paths.js'

const LIBRARY_LABEL = 'full-library'
const lastUrls = new Map<string, string>()

export function buildFullLibraryUrl(baseUrl: string): string {
  const base = baseUrl.trim()
  return base ? joinUrl(base, '/library') : ''
}

export async function openFullLibraryWindow(
  baseUrl: string,
): Promise<'opened' | 'focused' | 'browser'> {
  return openSiteLibraryWindow(buildFullLibraryUrl(baseUrl), LIBRARY_LABEL)
}

export async function openSiteLibraryWindow(
  url: string,
  label: string,
): Promise<'opened' | 'focused' | 'browser'> {
  if (!url) throw new Error('Set Server URL first.')

  if (!isTauriRuntime()) {
    window.open(
      url,
      label === LIBRARY_LABEL ? 'od-full-library' : 'od-thin-library',
      'width=1280,height=800',
    )
    return 'browser'
  }

  const existing = await WebviewWindow.getByLabel(label)
  if (existing) {
    if (lastUrls.get(label) !== url) {
      // Unknown windows can survive a reload of the main webview.
      await existing.close()
    } else {
      await existing.show()
      await existing.setFocus()
      lastUrls.set(label, url)
      return 'focused'
    }
  }

  const webview = new WebviewWindow(label, {
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
  lastUrls.set(label, url)
  return 'opened'
}

export function resetFullLibraryWindowForTests(): void {
  lastUrls.clear()
}
