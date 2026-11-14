import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { lazy, Suspense } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { AppErrorBoundary } from './AppErrorBoundary'

function BrokenView(): never {
  throw new Error('private component detail')
}

describe('AppErrorBoundary', () => {
  it('shows a safe recovery action after a render failure', () => {
    const onReload = vi.fn()
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    try {
      render(
        <AppErrorBoundary onReload={onReload}>
          <BrokenView />
        </AppErrorBoundary>,
      )
      expect(screen.getByRole('alert')).toHaveTextContent('Oneirodex hit a problem')
      expect(screen.queryByText('private component detail')).not.toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Reload Oneirodex' }))
      expect(onReload).toHaveBeenCalledOnce()
    } finally {
      consoleError.mockRestore()
    }
  })

  it('contains a rejected lazy import and keeps the recovery action accessible', async () => {
    const onReload = vi.fn()
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    const BrokenLazyView = lazy(async () => {
      throw new Error('private lazy chunk detail')
    })
    try {
      render(
        <AppErrorBoundary onReload={onReload}>
          <Suspense fallback={<p>Loading route</p>}>
            <BrokenLazyView />
          </Suspense>
        </AppErrorBoundary>,
      )

      const alert = await screen.findByRole('alert')
      expect(alert).toHaveTextContent('Oneirodex hit a problem')
      expect(screen.queryByText('private lazy chunk detail')).not.toBeInTheDocument()
      await waitFor(() =>
        expect(screen.getByRole('button', { name: 'Reload Oneirodex' })).toBeVisible(),
      )
      fireEvent.click(screen.getByRole('button', { name: 'Reload Oneirodex' }))
      expect(onReload).toHaveBeenCalledOnce()
    } finally {
      consoleError.mockRestore()
    }
  })
})
