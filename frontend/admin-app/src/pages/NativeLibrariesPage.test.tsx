import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NativeLibrariesPage } from './NativeLibrariesPage'

vi.mock('../components/Page', () => ({
  Page: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))
vi.mock('../components/LibrariesPanel', () => ({
  LibrariesPanel: () => <div data-testid="libraries-panel" />,
}))
vi.mock('../components/LibraryDoctorPanel', () => ({
  LibraryDoctorPanel: () => <div data-testid="doctor-panel" />,
}))
vi.mock('../components/RenameGamePanel', () => ({
  RenameGamePanel: () => <div data-testid="rename-panel" />,
}))
vi.mock('../components/LibraryFreshnessPanel', () => ({
  LibraryFreshnessPanel: () => <div data-testid="freshness-panel" />,
}))
vi.mock('../components/LibraryProposalsPanel', () => ({
  LibraryProposalsPanel: () => <div data-testid="proposals-panel" />,
}))
vi.mock('../hooks/useLibraryRefreshAll', () => ({
  useLibraryRefreshAll: () => ({
    conflictOpen: false,
    refreshing: false,
    startRefreshAll: vi.fn(),
    onConflictChoose: vi.fn(),
    onConflictClose: vi.fn(),
  }),
}))
vi.mock('../components/ScanConflictModal', () => ({
  ScanConflictModal: () => null,
}))

describe('NativeLibrariesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows library management before the maintenance panels', () => {
    render(
      <MemoryRouter>
        <NativeLibrariesPage />
      </MemoryRouter>,
    )

    const mainPanels = [
      'libraries-panel',
      'doctor-panel',
      'rename-panel',
      'freshness-panel',
      'proposals-panel',
    ]
    const renderedOrder = mainPanels
      .map((id) => ({ id, element: screen.getByTestId(id) }))
      .sort((a, b) =>
        a.element.compareDocumentPosition(b.element) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1,
      )
      .map(({ id }) => id)

    expect(renderedOrder).toEqual(mainPanels)
  })
})
