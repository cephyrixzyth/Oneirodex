import { vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { GameDetailsPage } from './GameDetailsPage'
import { stubFetch } from '../testJsonResponse'
import { showToast } from '../utils/toast'

vi.mock('../utils/toast', () => ({
  showToast: vi.fn(),
}))

vi.mock('../api/downloads', () => ({
  initiateGameDownload: vi.fn(),
}))

import { initiateGameDownload } from '../api/downloads'

const detailsPayload = {
  uuid: '11111111-1111-4111-8111-111111111111',
  name: 'Celeste',
  summary: 'Climb the mountain.',
  cover_url: '/static/newstyle/default_cover.jpg',
  size: '1.2 GB',
  developer: 'Maddy Makes Games',
  genres: ['Platform'],
  screenshots: ['/static/shot1.jpg', '/static/shot2.jpg'],
  urls: [{ type: 'youtube', url: 'https://www.youtube.com/watch?v=abc123DEF' }],
  video_urls: ['https://www.youtube.com/embed/abc123DEF'],
  lifecycle_state: 'downloaded',
  client_connected: true,
  playtime: { total_seconds: 3600, session_count: 2 },
  library_platform: 'PCWIN',
  library_platform_label: 'PC Windows',
}

beforeEach(() => {
  vi.mocked(showToast).mockReset()
  vi.mocked(initiateGameDownload).mockReset()
  stubFetch((url: any) => {
    if (String(url).includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(detailsPayload),
      })
    }
    if (String(url).includes('/versions')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            versions: [
              {
                kind: 'base',
                id: 1,
                uuid: detailsPayload.uuid,
                label: 'Base game',
                is_default: true,
              },
              {
                kind: 'extra',
                id: 2,
                uuid: 'extra-1',
                label: 'Extra: artbook',
                extra_kind: 'manual',
              },
            ],
          }),
      })
    }
    if (String(url).includes('/cheats')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ game_uuid: detailsPayload.uuid, cheats: [] }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })
})

function renderDetails(uuid = detailsPayload.uuid) {
  return render(
    <MemoryRouter initialEntries={[`/game_details/${uuid}`]}>
      <Routes>
        <Route path="/game_details/:gameUuid" element={<GameDetailsPage />} />
        <Route path="/library" element={<div>Library</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

test('loads game details into SPA page with action bar', async () => {
  renderDetails()

  expect(await screen.findByRole('heading', { name: 'Celeste' })).toBeInTheDocument()
  expect(screen.getByText('Climb the mountain.')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /^Install$/i })).toBeInTheDocument()
  expect(screen.getByText(/Base game/i)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Admin actions' })).toBeNull()
  expect(screen.queryByRole('heading', { name: 'Cheats' })).toBeNull()
  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalled()
  })
})

test('shows Cheats panel only when cheat_surface is retroarch', async () => {
  stubFetch((url: any) => {
    if (String(url).includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...detailsPayload,
            library_platform: 'SNES',
            library_platform_label: 'Super Nintendo',
            cheat_surface: 'retroarch',
            can_play_in_browser: true,
            emulator_core: 'snes9x',
            emulator_cores: ['snes9x'],
          }),
      })
    }
    if (String(url).includes('/versions')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ versions: [] }),
      })
    }
    if (String(url).includes('/cheats')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ game_uuid: detailsPayload.uuid, cheats: [] }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })

  renderDetails()
  expect(await screen.findByRole('heading', { name: 'Cheats' })).toBeInTheDocument()
  const playLinks = screen.getAllByRole('link', { name: /Play in browser/i })
  expect(playLinks.length).toBeGreaterThanOrEqual(1)
  expect(playLinks[0]).toHaveAttribute('href', expect.stringContaining('cheat_surface=retroarch'))
})

test('Play link keeps the Nostalgist NES host from play_url', async () => {
  stubFetch((url: any) => {
    if (String(url).includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...detailsPayload,
            library_platform: 'NES',
            library_platform_label: 'NES',
            can_play_in_browser: true,
            play_url:
              '/static/vendor/nostalgist/play.html?guid=11111111-1111-4111-8111-111111111111&core=nestopia&platform=NES',
            emulator_core: 'nestopia',
            emulator_cores: ['nestopia', 'fceumm'],
          }),
      })
    }
    if (String(url).includes('/versions')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ versions: [] }),
      })
    }
    if (String(url).includes('/cheats')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ game_uuid: detailsPayload.uuid, cheats: [] }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })

  renderDetails()
  const play = await screen.findByRole('link', { name: /Play in browser/i })
  expect(play.getAttribute('href')).toContain('/static/vendor/nostalgist/play.html')
  expect(play.getAttribute('href')).toContain('core=nestopia')
  expect(play.getAttribute('href')).not.toContain('webretro.html')
})

test('shows disc chips on details, not as a tile badge', async () => {
  stubFetch((url: any) => {
    if (String(url).includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...detailsPayload,
            is_multi_disc: true,
            disc_count: 2,
            discs: [
              { disc_index: 1, is_primary: true },
              { disc_index: 2, is_primary: false },
            ],
          }),
      })
    }
    if (String(url).includes('/versions')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ versions: [] }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })

  renderDetails()
  expect(await screen.findByRole('heading', { name: 'Celeste' })).toBeInTheDocument()
  expect(screen.getByText('2 discs')).toBeInTheDocument()
  expect(screen.getByText('Disc 1')).toBeInTheDocument()
  expect(screen.getByText('Disc 2')).toBeInTheDocument()
})

test('admin path rows show the full library folder string', async () => {
  const fullPath = '/mnt/user/games/PCWIN/Indie Puzzle/Very Long Folder Name/Celeste'
  stubFetch((url: any) => {
    if (String(url).includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...detailsPayload,
            is_admin: true,
            full_disk_path: fullPath,
            server_path: fullPath,
          }),
      })
    }
    if (String(url).includes('/versions')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ versions: [] }),
      })
    }
    if (String(url).includes('/cheats')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ game_uuid: detailsPayload.uuid, cheats: [] }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })

  renderDetails()
  expect(await screen.findByText(fullPath)).toBeInTheDocument()
  expect(screen.getByLabelText('Admin paths')).toBeInTheDocument()
  const pathValue = document.querySelector('.od-details-page__path-value')
  expect(pathValue?.textContent).toBe(fullPath)
})

test('admin ⋮ menu exposes Edit Details / Edit Images', async () => {
  const user = userEvent.setup()
  stubFetch((url: any) => {
    if (String(url).includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...detailsPayload,
            is_admin: true,
            full_disk_path: '/games/Celeste',
            server_path: '/mnt/user/games/Celeste',
          }),
      })
    }
    if (String(url).includes('/versions')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ versions: [] }),
      })
    }
    if (String(url).includes('/cheats')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ game_uuid: detailsPayload.uuid, cheats: [] }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })

  const { container } = renderDetails()

  expect(await screen.findByRole('heading', { name: 'Celeste' })).toBeInTheDocument()
  const coverWrap = container.querySelector('.od-details-page__cover-wrap')
  expect(coverWrap).toBeTruthy()
  const adminBtn = within(coverWrap! as HTMLElement).getByRole('button', { name: 'Admin actions' })
  expect(adminBtn).toHaveAttribute('data-chrome-anchor', 'top-right')
  expect(
    container.querySelector('.od-details-page__hero-main .od-details-page__admin-menu'),
  ).toBeNull()
  await user.click(adminBtn)
  expect(
    within(coverWrap! as HTMLElement).getByRole('menuitem', { name: 'Edit Details' }),
  ).toHaveFocus()
  expect(
    within(coverWrap! as HTMLElement).getByRole('menuitem', { name: 'Edit Details' }),
  ).toHaveAttribute('href', `/game_edit/${detailsPayload.uuid}`)
  expect(
    within(coverWrap! as HTMLElement).getByRole('menuitem', { name: 'Edit Images' }),
  ).toHaveAttribute('href', `/edit_game_images/${detailsPayload.uuid}`)
  await user.keyboard('{ArrowDown}')
  expect(
    within(coverWrap! as HTMLElement).getByRole('menuitem', { name: 'Edit Images' }),
  ).toHaveFocus()
  await user.keyboard('{Escape}')
  expect(adminBtn).toHaveFocus()
  expect(within(coverWrap! as HTMLElement).queryByRole('menu')).toBeNull()
  expect(screen.getByText('/games/Celeste')).toBeInTheDocument()
  expect(screen.getByText('/mnt/user/games/Celeste')).toBeInTheDocument()
  expect(screen.getByLabelText('Admin paths')).toBeInTheDocument()
})

/**
 * The stage is the only gallery.
 *
 * There used to be a second Screenshots grid and a second Trailers & videos
 * list at the foot of the page showing exactly what the stage already shows.
 * Both are gone, along with the Theater and Fullscreen buttons: clicking the
 * still opens the lightbox, and a trailer uses the player's own fullscreen.
 */
test('media stage is the only gallery and its still opens the lightbox', async () => {
  const user = userEvent.setup()
  renderDetails()

  expect(await screen.findByTitle('Primary trailer')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Extras & DLC' })).toBeInTheDocument()
  expect(screen.getByText(/Extra: artbook/i)).toBeInTheDocument()

  expect(screen.queryByRole('heading', { name: 'Trailers & videos' })).toBeNull()
  expect(screen.queryByRole('heading', { name: 'Screenshots' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Theater' })).toBeNull()
  expect(screen.queryByRole('button', { name: 'Fullscreen' })).toBeNull()

  await user.click(screen.getByRole('button', { name: 'Show screenshot 1' }))
  await user.click(screen.getByRole('button', { name: 'Open screenshot in viewer' }))
  expect(screen.getByRole('heading', { name: /Screenshot 1/i })).toBeInTheDocument()
})

/**
 * The viewer must not render inside the article.
 *
 * `.od-details-page > :not(.od-details-page__backdrop)` lifts every child of
 * the page above the backdrop with `position: relative`, and that beat
 * `.od-lightbox`'s `position: fixed` on specificity — so the "popup" laid
 * itself out in the page flow at the foot of the article. Portalling to body
 * puts it out of reach of any host page's stacking rules.
 */
test('the screenshot viewer portals out of the details page', async () => {
  const user = userEvent.setup()
  renderDetails()

  expect(await screen.findByTitle('Primary trailer')).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: 'Show screenshot 1' }))
  await user.click(screen.getByRole('button', { name: 'Open screenshot in viewer' }))

  const lightbox = document.querySelector('.od-lightbox')
  expect(lightbox).toBeTruthy()
  expect(document.querySelector('.od-details-page')!.contains(lightbox)).toBe(false)
  expect(lightbox!.parentElement).toBe(document.body)
})

test('prefers trailers[].embed_url and shows extras from details payload', async () => {
  stubFetch((url: any) => {
    if (String(url).includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...detailsPayload,
            video_urls: [],
            urls: [],
            has_trailers: true,
            trailers: [
              {
                url: 'https://www.youtube.com/watch?v=abc123DEF',
                embed_url: 'https://www.youtube.com/embed/abc123DEF',
                provider: 'youtube',
              },
            ],
            extras: [
              {
                uuid: 'extra-payload',
                name: 'Artbook PDF',
                type: 'manual',
                extra_kind: 'manual',
                on_server: true,
                download_url:
                  '/download_other/extra/11111111-1111-4111-8111-111111111111/extra-payload',
              },
            ],
          }),
      })
    }
    if (String(url).includes('/versions')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ versions: [] }),
      })
    }
    if (String(url).includes('/cheats')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ game_uuid: detailsPayload.uuid, cheats: [] }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })

  renderDetails()

  expect(await screen.findByTitle('Primary trailer')).toHaveAttribute(
    'src',
    'https://www.youtube.com/embed/abc123DEF',
  )
  expect(screen.getByText('Artbook PDF')).toBeInTheDocument()
  expect(screen.getByText(/On server/i)).toBeInTheDocument()
  expect(screen.queryByText(/Backend extras/i)).toBeNull()
})

test('shows youtube_demo_url when no trailers exist', async () => {
  stubFetch((url: any) => {
    if (String(url).includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...detailsPayload,
            video_urls: [],
            urls: [],
            trailers: [],
            has_trailers: false,
            youtube_demo_url: 'https://youtu.be/demoOnly99',
          }),
      })
    }
    if (String(url).includes('/versions')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ versions: [] }),
      })
    }
    if (String(url).includes('/cheats')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ game_uuid: detailsPayload.uuid, cheats: [] }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })

  renderDetails()

  expect(await screen.findByRole('link', { name: 'YouTube demo' })).toHaveAttribute(
    'href',
    'https://youtu.be/demoOnly99',
  )
  expect(screen.queryByTitle('Primary trailer')).toBeNull()
})

/**
 * The base row no longer carries a Download.
 *
 * Downloading the base game is the action bar's primary button at the top of
 * the page, so this row was a second, quieter copy of the loudest control on
 * the page — under a heading about versions, which is not what it was for.
 * Per-*update* download stays, because it is the one thing the action bar
 * cannot express: "I have the game, I only need patch 1.03".
 *
 * The fixture gains a downloadable update so all three cases are covered at
 * once: base (never), update-downloadable (yes), update-missing (no).
 */
test('versions: base has no Download; a downloadable update does; missing hides it', async () => {
  stubFetch((url: any) => {
    if (String(url).includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(detailsPayload),
      })
    }
    if (String(url).includes('/versions')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            versions: [
              {
                kind: 'base',
                id: 1,
                uuid: detailsPayload.uuid,
                label: 'Base game',
                is_default: true,
                downloadable: true,
                size: '1.2 GB',
              },
              {
                kind: 'update',
                id: 2,
                uuid: 'update-missing',
                label: 'Update: gone.bin',
                is_default: false,
                path_missing: true,
                downloadable: false,
                size: null,
              },
              {
                kind: 'update',
                id: 3,
                uuid: 'update-ready',
                label: 'Update: patch-1.03.bin',
                is_default: false,
                downloadable: true,
                size: '40 MB',
              },
            ],
          }),
      })
    }
    if (String(url).includes('/cheats')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ game_uuid: detailsPayload.uuid, cheats: [] }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })

  renderDetails()

  expect(await screen.findByRole('heading', { name: 'Versions' })).toBeInTheDocument()
  expect(screen.getByText('Default')).toBeInTheDocument()
  const versionsSection = document.getElementById('updates')
  expect(versionsSection).toBeTruthy()
  expect(versionsSection).toHaveTextContent('1.2 GB')
  // Exactly one: the downloadable update. Not the base row, not the missing one.
  const downloadButtons = within(versionsSection!).getAllByRole('button', { name: 'Download' })
  expect(downloadButtons).toHaveLength(1)
  // …and it is the one attached to the update, which is what makes this a test
  // of the rule rather than of the count.
  expect(downloadButtons[0].closest('li')?.textContent).toMatch(/patch-1\.03\.bin/)
  expect(within(versionsSection!).getByText(/Missing on disk/i)).toBeInTheDocument()
  expect(within(versionsSection!).getByText(/Update: gone\.bin/i)).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Remove missing versions/i })).toBeNull()
})

test('firmware_missing blocks Play and shows quiet honesty with Help link', async () => {
  stubFetch((url: any) => {
    if (String(url).includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...detailsPayload,
            can_play_in_browser: true,
            play_url: '/static/vendor/webretro/webretro.html?guid=111&core=yabause',
            emulator_core: 'yabause',
            emulator_cores: ['yabause'],
            bios_required: true,
            firmware_missing: true,
            bios: {
              message: 'yabause needs BIOS under Admin → emulator BIOS (missing: saturn_bios.bin)',
              hint: 'Upload legally obtained firmware via Admin → emulator BIOS',
            },
          }),
      })
    }
    if (String(url).includes('/versions')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ versions: [] }),
      })
    }
    if (String(url).includes('/cheats')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ game_uuid: detailsPayload.uuid, cheats: [] }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })

  renderDetails()

  expect(await screen.findByRole('heading', { name: 'Celeste' })).toBeInTheDocument()
  const play = screen.getByRole('button', { name: /Play in browser/i })
  expect(play).toBeDisabled()
  expect(play).toHaveAttribute(
    'title',
    'yabause needs BIOS under Admin → emulator BIOS (missing: saturn_bios.bin)',
  )
  expect(screen.queryByRole('link', { name: /Play in browser/i })).toBeNull()
  expect(screen.getByText(/yabause needs BIOS under Admin/i)).toBeInTheDocument()
  expect(screen.getByText(/Upload legally obtained firmware via Admin/i)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Help → Browser play/i })).toHaveAttribute(
    'href',
    '/help#browser-play',
  )
  expect(screen.queryByRole('link', { name: /Download BIOS/i })).toBeNull()
  expect(screen.queryByText(/Download BIOS/i)).toBeNull()
})

test('version download toasts Backend hint on 410 path_missing', async () => {
  const user = userEvent.setup()
  const err = new Error('This install path is gone')
  ;(err as any).status = 410
  ;(err as any).code = 'path_missing'
  ;(err as any).hint = 'Use game details → Remove missing versions'
  ;(err as any).data = {
    code: 'path_missing',
    hint: (err as any).hint,
    error: 'Version file is missing on disk',
  }
  vi.mocked(initiateGameDownload).mockRejectedValue(err)

  stubFetch((url: any) => {
    if (String(url).includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(detailsPayload),
      })
    }
    if (String(url).includes('/versions')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            versions: [
              {
                kind: 'base',
                id: 1,
                uuid: detailsPayload.uuid,
                label: 'Base game',
                is_default: true,
                downloadable: true,
              },
              // The row that still has a Download button to press. Base no
              // longer does — see the versions test above.
              {
                kind: 'update',
                id: 2,
                uuid: 'update-ready',
                label: 'Update: patch-1.03.bin',
                is_default: false,
                downloadable: true,
              },
            ],
          }),
      })
    }
    if (String(url).includes('/cheats')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ game_uuid: detailsPayload.uuid, cheats: [] }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })

  renderDetails()
  expect(await screen.findByRole('heading', { name: 'Versions' })).toBeInTheDocument()
  await user.click(
    within(document.getElementById('updates')!).getByRole('button', { name: 'Download' }),
  )
  await waitFor(() => {
    expect(initiateGameDownload).toHaveBeenCalledWith(detailsPayload.uuid, {
      kind: 'update',
      versionUuid: 'update-ready',
    })
  })
  expect(showToast).toHaveBeenCalledWith('Use game details → Remove missing versions', 'error')
})

test('admin can remove missing versions via cleanup_orphans', async () => {
  const user = userEvent.setup()
  stubFetch((url: any, options = {}) => {
    const href = String(url)
    if (href.includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...detailsPayload,
            is_admin: true,
          }),
      })
    }
    if (href.includes('/versions/cleanup_orphans')) {
      expect((options as any).method).toBe('POST')
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ removed: 1, message: 'Removed 1 missing version' }),
      })
    }
    if (href.includes('/versions')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            versions: [
              {
                kind: 'base',
                id: 1,
                uuid: detailsPayload.uuid,
                label: 'Base game',
                is_default: true,
                downloadable: true,
              },
              {
                kind: 'update',
                id: 2,
                uuid: 'update-missing',
                label: 'Update: orphan.bin',
                path_missing: true,
                downloadable: false,
              },
            ],
          }),
      })
    }
    if (href.includes('/cheats')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ game_uuid: detailsPayload.uuid, cheats: [] }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })

  renderDetails()

  expect(
    await screen.findByRole('button', { name: /Remove missing versions/i }),
  ).toBeInTheDocument()
  await user.click(screen.getByRole('button', { name: /Remove missing versions/i }))
  await waitFor(() => {
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/versions/cleanup_orphans'),
      expect.objectContaining({ method: 'POST' }),
    )
  })
  const versionsSection = document.getElementById('updates')
  expect(within(versionsSection!).getByRole('status')).toHaveTextContent(
    /Removed 1 missing version/i,
  )
})

/**
 * Summary and Details read down the left of the fold, media sits to their
 * right, and everything after that runs full width below — so the flow is a
 * sibling of the fold, not a third column inside the content grid.
 */
test('summary and facts share the fold with the media stage', async () => {
  renderDetails()

  expect(await screen.findByRole('heading', { name: 'Celeste' })).toBeInTheDocument()
  const fold = document.querySelector('.od-details-page__fold')
  expect(fold).toBeTruthy()
  const grid = fold!.querySelector('.od-details-page__content-grid')
  expect(grid).toBeTruthy()
  expect(grid!.querySelector('.od-details-page__section--summary')).toBeTruthy()
  expect(grid!.querySelector('.od-details-page__section--facts')).toBeTruthy()
  expect(fold!.querySelector('.od-details-media')).toBeTruthy()

  const flow = document.querySelector('.od-details-page__flow')
  expect(flow).toBeTruthy()
  expect(grid!.contains(flow)).toBe(false)
  expect(
    within(flow! as HTMLElement).getByRole('heading', { name: 'Versions' }),
  ).toBeInTheDocument()
  expect(
    within(flow! as HTMLElement).getByRole('heading', { name: 'Extras & DLC' }),
  ).toBeInTheDocument()
})

test('facts rail stays in the grid when there is no summary', async () => {
  stubFetch((url: any) => {
    if (String(url).includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ ...detailsPayload, summary: '' }),
      })
    }
    if (String(url).includes('/versions')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            versions: [
              {
                kind: 'base',
                id: 1,
                uuid: detailsPayload.uuid,
                label: 'Base game',
                is_default: true,
              },
            ],
          }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })

  renderDetails()

  expect(await screen.findByRole('heading', { name: 'Celeste' })).toBeInTheDocument()
  const grid = document.querySelector('.od-details-page__content-grid')
  expect(grid!.querySelector('.od-details-page__section--summary')).toBeNull()
  expect(grid!.querySelector('.od-details-page__section--facts')).toBeTruthy()
  const flow = document.querySelector('.od-details-page__flow')
  expect(
    within(flow! as HTMLElement).getByRole('heading', { name: 'Versions' }),
  ).toBeInTheDocument()
})

test('breadcrumb is Catalog then primary genre then title', async () => {
  renderDetails()

  const crumbs = await screen.findByRole('navigation', { name: 'Breadcrumb' })
  expect(within(crumbs).getByRole('link', { name: 'Game Catalog' })).toHaveAttribute(
    'href',
    '/library',
  )
  expect(within(crumbs).getByRole('link', { name: 'Platform' })).toHaveAttribute(
    'href',
    '/library?genre=Platform',
  )
  expect(within(crumbs).getByText('Celeste')).toBeInTheDocument()
})

test('console leaf breadcrumb starts at Systems', async () => {
  stubFetch((url: any) => {
    if (String(url).includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...detailsPayload,
            library_platform: 'NES',
            library_platform_label: 'NES',
          }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })

  renderDetails()

  const crumbs = await screen.findByRole('navigation', { name: 'Breadcrumb' })
  expect(within(crumbs).getByRole('link', { name: 'Systems' })).toHaveAttribute('href', '/systems')
})

test('renders About, capability chips, and store specs when present', async () => {
  stubFetch((url: any) => {
    if (String(url).includes('/details')) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...detailsPayload,
            storyline: 'A mountain, a bird, and a lot of climbing.',
            game_modes: ['Single-player'],
            player_perspectives: ['Side view'],
            themes: ['Action'],
            store_specs: {
              system_requirements: { windows: { minimum: 'Windows 7' } },
              languages: [{ name: 'English', interface: true, audio: true, subtitles: true }],
            },
          }),
      })
    }
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) })
  })

  renderDetails()

  expect(await screen.findByRole('heading', { name: 'About' })).toBeInTheDocument()
  expect(screen.getByText('A mountain, a bird, and a lot of climbing.')).toBeInTheDocument()
  expect(screen.getAllByRole('link', { name: 'Single-player' })[0]).toHaveAttribute(
    'href',
    '/library?game_mode=Single-player',
  )
  expect(screen.getAllByRole('link', { name: 'Side view' })[0]).toHaveAttribute(
    'href',
    '/library?player_perspective=Side%20view',
  )
  expect(screen.getAllByRole('link', { name: 'Action' })[0]).toHaveAttribute(
    'href',
    '/library?theme=Action',
  )
  expect(screen.getByRole('heading', { name: 'System requirements' })).toBeInTheDocument()
  expect(screen.getByText('Windows 7')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Store languages' })).toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: 'Audio' })).toBeInTheDocument()
})

test('media stage sits beside the summary when trailers exist', async () => {
  renderDetails()

  expect(await screen.findByTitle('Primary trailer')).toHaveAttribute(
    'src',
    'https://www.youtube.com/embed/abc123DEF',
  )
  expect(document.querySelector('.od-details-page__fold--media')).toBeTruthy()
  expect(document.querySelector('.od-details-page__content-grid')).toBeTruthy()
})
