/**
 * Single-player assist packs (Wand-inspired) for the desktop companion.
 * Policy: offline / single-player only — packs are declarative toggles, not injectors.
 */

import { formatBearerAuthorization } from '@oneirodex/api-client'

import type { AuthStore } from './auth.js'
import { escapeHtml } from './html.js'

export interface AssistToggle {
  id: string
  label: string
  description?: string
}

export interface AssistPack {
  game_uuid: string
  title: string
  policy: string
  toggles: AssistToggle[]
}

export async function fetchAssistPack(
  auth: AuthStore,
  gameUuid: string,
  options: { fetchImpl?: typeof fetch } = {},
): Promise<AssistPack | null> {
  const baseUrl = auth.getBaseUrl()
  const token = auth.getToken()
  if (!baseUrl || !token) {
    return null
  }
  const fetchImpl = options.fetchImpl ?? fetch
  const response = await fetchImpl(
    `${baseUrl.replace(/\/$/, '')}/api/games/${encodeURIComponent(gameUuid)}/assists`,
    {
      headers: { Authorization: formatBearerAuthorization(token) },
      redirect: 'error',
    },
  )
  if (!response.ok) {
    return null
  }
  const data = (await response.json().catch(() => ({}))) as {
    enabled?: boolean
    pack?: AssistPack | null
  }
  if (!data.enabled || !data.pack) {
    return null
  }
  return data.pack
}

export function renderAssistOverlay(
  pack: AssistPack,
  onToggle: (id: string, enabled: boolean) => void,
): HTMLElement {
  const root = document.createElement('div')
  root.className = 'od-assist-overlay'
  // Escaped, like every other innerHTML site in this client: `pack` is server
  // data, and this runs inside a Tauri webview with IPC reach.
  root.innerHTML =
    `<h3>${escapeHtml(pack.title)}</h3>` + `<p class="muted">${escapeHtml(pack.policy)}</p>`
  const list = document.createElement('ul')
  for (const toggle of pack.toggles) {
    const item = document.createElement('li')
    const label = document.createElement('label')
    const input = document.createElement('input')
    input.type = 'checkbox'
    input.addEventListener('change', () => onToggle(toggle.id, input.checked))
    label.append(input, document.createTextNode(` ${toggle.label}`))
    item.append(label)
    if (toggle.description) {
      const hint = document.createElement('span')
      hint.className = 'muted'
      hint.textContent = toggle.description
      item.append(hint)
    }
    list.append(item)
  }
  root.append(list)
  return root
}
