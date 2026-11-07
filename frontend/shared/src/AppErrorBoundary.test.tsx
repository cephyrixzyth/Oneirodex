import { fireEvent, render, screen } from '@testing-library/react'
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
})
