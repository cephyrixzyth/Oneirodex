import { csrfHeaders } from './csrf.js'
import { errorFromResponse } from './envelopeError.js'

export interface PreferenceChoice {
  value: string
  label: string
}
export interface ThemeChoice {
  slug: string
  name: string
  description?: string
  era: string
  icon_pack?: string
}
export interface ThemeGroup {
  id: string
  label: string
  hint?: string
  items: ThemeChoice[]
}
export interface PreferencesPayload {
  preferences: Record<string, string>
  choices: {
    items_per_page: PreferenceChoice[]
    default_sort: PreferenceChoice[]
    default_sort_order: PreferenceChoice[]
    themes: ThemeGroup[]
    icon_packs: Array<{ id: string; name: string }>
    fonts: PreferenceChoice[]
    browser_player_engines: PreferenceChoice[]
    game_locales: PreferenceChoice[]
  }
  member_engine_choice: boolean
  is_admin: boolean
}

async function checked<T>(response: Response, label: string): Promise<T> {
  if (!response.ok) throw await errorFromResponse(response, label)
  return response.json() as Promise<T>
}

export async function getPreferences(signal?: AbortSignal): Promise<PreferencesPayload> {
  const response = await fetch('/api/account/preferences', { credentials: 'same-origin', signal })
  return checked(response, 'preferences load failed')
}

export async function putPreferences(
  values: Record<string, string | number | boolean>,
): Promise<{ preferences: Record<string, string> }> {
  const response = await fetch('/api/account/preferences', {
    method: 'PUT',
    credentials: 'same-origin',
    headers: csrfHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(values),
  })
  return checked(response, 'preferences save failed')
}
