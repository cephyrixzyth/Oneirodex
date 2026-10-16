import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { PreferencesModal } from '@oneirodex/ui'

const preferenceResponse = {
  preferences: {
    items_per_page: '50',
    default_sort: 'name',
    default_sort_order: 'asc',
    theme: 'default',
    icon_pack: 'outline',
    font: 'system-ui',
    tile_size: '50',
    show_tile_titles: 'true',
    browser_player_engine: '',
    preferred_game_locale: 'en-US',
  },
  choices: {
    items_per_page: [
      { value: '50', label: '50' },
      { value: '100', label: '100' },
    ],
    default_sort: [
      { value: 'name', label: 'Name' },
      { value: 'rating', label: 'Rating' },
    ],
    default_sort_order: [{ value: 'asc', label: 'Ascending' }],
    themes: [
      {
        id: 'cabinet',
        label: 'Colour cabinets',
        items: [{ slug: 'default', name: 'Default', era: '90s' }],
      },
    ],
    icon_packs: [
      { id: 'outline', name: 'Outline' },
      { id: 'solid', name: 'Solid' },
    ],
    fonts: [{ value: 'system-ui', label: 'System UI' }],
    browser_player_engines: [{ value: '', label: 'Server default' }],
    game_locales: [{ value: 'en-US', label: 'English (US)' }],
  },
  member_engine_choice: false,
  is_admin: false,
}

afterEach(() => vi.unstubAllGlobals())

it('loads unified choices and saves changed preferences through the JSON API', async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(preferenceResponse), { status: 200 }))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ok: true,
          preferences: {
            ...preferenceResponse.preferences,
            items_per_page: '100',
            icon_pack: 'solid',
          },
        }),
        { status: 200 },
      ),
    )
  vi.stubGlobal('fetch', fetchMock)
  render(<PreferencesModal open onClose={() => undefined} />)

  fireEvent.change(await screen.findByLabelText('Max items per page'), { target: { value: '100' } })
  fireEvent.click(screen.getByRole('button', { name: 'Solid' }))
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  expect(screen.getByRole('status')).toHaveTextContent('Preferences saved.')
  const [, options] = fetchMock.mock.calls[1]
  expect(options.method).toBe('PUT')
  expect(JSON.parse(options.body)).toMatchObject({ items_per_page: '100', icon_pack: 'solid' })
})
