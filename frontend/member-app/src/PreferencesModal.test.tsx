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

it('shows and saves an uploaded operator font from the server-provided choices', async () => {
  const uploadedFont = { value: 'paritycollision', label: 'ParityCollision (operator)' }
  const withUploadedFont = {
    ...preferenceResponse,
    choices: {
      ...preferenceResponse.choices,
      fonts: [...preferenceResponse.choices.fonts, uploadedFont],
    },
  }
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(withUploadedFont), { status: 200 }))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ok: true,
          preferences: { ...preferenceResponse.preferences, font: uploadedFont.value },
        }),
        { status: 200 },
      ),
    )
  vi.stubGlobal('fetch', fetchMock)
  render(<PreferencesModal open onClose={() => undefined} />)

  const font = await screen.findByLabelText('Font')
  expect(screen.getByRole('option', { name: uploadedFont.label })).toBeInTheDocument()
  fireEvent.change(font, { target: { value: uploadedFont.value } })
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  expect(screen.getByRole('status')).toHaveTextContent('Preferences saved.')
  const [, options] = fetchMock.mock.calls[1]
  expect(options.method).toBe('PUT')
  expect(JSON.parse(options.body)).toMatchObject({ font: uploadedFont.value })
})

it('saves a theme when its paired icon pack is not installed', async () => {
  const withUninstalledThemeIcon = {
    ...preferenceResponse,
    choices: {
      ...preferenceResponse.choices,
      themes: [
        {
          id: 'cabinet',
          label: 'Colour cabinets',
          items: [
            { slug: 'default', name: 'Default', era: '90s', icon_pack: 'outline' },
            {
              slug: 'deep-space',
              name: 'Deep Space Media',
              era: 'media_center_00s',
              icon_pack: 'angular',
            },
          ],
        },
      ],
    },
  }
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(withUninstalledThemeIcon), { status: 200 }))
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          ok: true,
          preferences: {
            ...preferenceResponse.preferences,
            theme: 'deep-space',
          },
        }),
        { status: 200 },
      ),
    )
  vi.stubGlobal('fetch', fetchMock)
  render(<PreferencesModal open onClose={() => undefined} />)

  fireEvent.click(await screen.findByRole('button', { name: /Deep Space Media/ }))
  expect(screen.getByRole('button', { name: 'Outline' })).toHaveAttribute('aria-pressed', 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  expect(screen.getByRole('status')).toHaveTextContent('Preferences saved.')
  const [, options] = fetchMock.mock.calls[1]
  expect(JSON.parse(options.body)).toMatchObject({ theme: 'deep-space', icon_pack: 'outline' })
})
