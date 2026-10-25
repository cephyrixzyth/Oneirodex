import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { confirmAction, openPreferencesModal } from '@oneirodex/ui'
import { deleteJson, getJson, postForm, postJson, putJson } from '../api/adminApi'
import { ThemesPage } from './ThemesPage'

vi.mock('../api/adminApi', () => ({
  getJson: vi.fn(),
  deleteJson: vi.fn(),
  postForm: vi.fn(),
  postJson: vi.fn(),
  putJson: vi.fn(),
}))
vi.mock('@oneirodex/ui', async (original) => ({
  ...(await original()),
  confirmAction: vi.fn(),
  openPreferencesModal: vi.fn(),
}))

const themes = {
  active_theme: 'default',
  default_theme: { name: 'Default' },
  themes: [
    { folder: 'default', name: 'Default', author: 'Oneirodex', description: 'Bundled' },
    { folder: 'night-green', name: 'Night Green', author: 'Mina', description: 'Dark green' },
  ],
}
const icons = {
  loading_icon_mode: 'rotate',
  loading_icon_id: null,
  catalogue: [
    { id: 'dpad', name: 'D-pad', family: 'Classic', description: 'Directional pad' },
    { id: 'arcade', name: 'Arcade', family: 'Systems', description: 'Cabinet' },
  ],
}
function mockLoad() {
  vi.mocked(getJson).mockImplementation(async (url) =>
    url.endsWith('/loading-icons') ? icons : themes,
  )
}

describe('ThemesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    delete window.GtLoadingMotifs
    mockLoad()
  })

  it('shows active and installed themes, grouped motifs, authoring and preferences links', async () => {
    render(<ThemesPage />)
    expect(await screen.findByText('Default is active for your account.')).toBeInTheDocument()
    expect(screen.getByText('Night Green')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Use one motif'))
    expect(screen.getByRole('group', { name: 'Classic' })).toHaveTextContent('D-pad')
    expect(screen.getByRole('link', { name: 'Theme authoring guide' })).toHaveAttribute(
      'href',
      '/admin/themes/readme',
    )
    const preferences = screen.getByRole('button', { name: 'Choose your theme in Preferences' })
    fireEvent.click(preferences)
    expect(openPreferencesModal).toHaveBeenCalledOnce()
  })

  it('saves the selected loading motif and exposes a locked picker', async () => {
    vi.mocked(putJson).mockResolvedValue({})
    render(<ThemesPage />)
    fireEvent.click(await screen.findByLabelText('Use one motif'))
    fireEvent.change(screen.getByLabelText('Motif'), { target: { value: 'arcade' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save loading motif' }))
    await waitFor(() =>
      expect(putJson).toHaveBeenCalledWith('/api/admin/loading-icon/config', {
        loading_icon_mode: 'lock',
        loading_icon_id: 'arcade',
      }),
    )
  })

  it('previews the rotating catalogue and reports the full rotation size', async () => {
    const motifIds = ['dpad', 'disc', 'stick', 'handheld', 'cart', 'crt']
    const buildNode = vi.fn((id: string, sizeClass = '') => {
      const node = document.createElement('span')
      node.className = `od-loading-motif ${sizeClass}`.trim()
      node.dataset.motif = id
      node.setAttribute('aria-hidden', 'true')
      return node
    })
    window.GtLoadingMotifs = { CATALOGUE: motifIds, buildNode }
    vi.mocked(getJson).mockImplementation(async (url) =>
      url.endsWith('/loading-icons')
        ? {
            ...icons,
            catalogue: [
              ...icons.catalogue,
              ...motifIds.slice(2).map((id) => ({ id, name: id, family: 'Classic' })),
              { id: 'nes', name: 'NES', family: 'Nintendo' },
            ],
          }
        : themes,
    )

    render(<ThemesPage />)

    const preview = await screen.findByRole('group', { name: 'Rotating motif previews' })
    expect(
      screen.getByText(/random motif per session; lock pins one for everyone/i),
    ).toBeInTheDocument()
    await waitFor(() => expect(preview.querySelectorAll('[data-motif]')).toHaveLength(6))
    expect(preview).toHaveTextContent('Rotating across 7 motifs')
    expect(preview.querySelector('[data-motif="dpad"]')).toHaveAttribute('tabindex', '0')
    expect(preview.querySelector('[data-motif="dpad"]')).toHaveAttribute('aria-label', 'D-pad')
    expect(buildNode).toHaveBeenCalledWith(
      'dpad',
      'od-loading-motif--sm od-loading-motif--preview',
    )

    fireEvent.click(screen.getByLabelText('Use one motif'))
    await waitFor(() => expect(preview.querySelectorAll('[data-motif]')).toHaveLength(1))
    expect(preview.querySelector('[data-motif="dpad"]')).toHaveClass('od-loading-motif--lg')
  })

  it('uploads a selected ZIP through multipart without setting content type in the page', async () => {
    vi.mocked(postForm).mockResolvedValue({})
    render(<ThemesPage />)
    const input = (await screen.findByLabelText('Theme ZIP')) as HTMLInputElement
    const file = new File(['PK archive'], 'theme.zip', { type: 'application/zip' })
    fireEvent.change(input, { target: { files: [file] } })
    fireEvent.click(screen.getByRole('button', { name: 'Upload theme' }))
    await waitFor(() =>
      expect(postForm).toHaveBeenCalledWith('/api/admin/themes', expect.any(FormData)),
    )
  })

  it('requires confirmation before delete and reset actions', async () => {
    vi.mocked(confirmAction).mockResolvedValue(false)
    render(<ThemesPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }))
    await waitFor(() => expect(confirmAction).toHaveBeenCalled())
    expect(deleteJson).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Reset Default Themes' }))
    await waitFor(() => expect(confirmAction).toHaveBeenCalledTimes(2))
    expect(postJson).not.toHaveBeenCalled()
  })

  it('retries failed loading and retains a clear error state', async () => {
    vi.mocked(getJson)
      .mockRejectedValueOnce(new Error('Offline'))
      .mockRejectedValueOnce(new Error('Offline'))
    render(<ThemesPage />)
    fireEvent.click(await screen.findByRole('button', { name: 'Retry loading themes' }))
    await waitFor(() => expect(getJson).toHaveBeenCalledTimes(4))
    expect(await screen.findByText('Night Green')).toBeInTheDocument()
  })
})
