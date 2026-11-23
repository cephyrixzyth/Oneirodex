import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider, Link, Routes, Route } from 'react-router-dom'
import userEvent from '@testing-library/user-event'
import { expect, test, vi } from 'vitest'
import { MoonfallNavigationGuard } from './MoonfallNavigationGuard'
test('waits for progress acknowledgement before leaving a nested route', async () => {
  let resolve!: (value: boolean) => void
  const beforeLeave = vi.fn(
    () =>
      new Promise<boolean>((done) => {
        resolve = done
      }),
  )
  const session = { hasUnsaved: () => true, beforeLeave }
  const router = createMemoryRouter(
    [
      {
        path: '*',
        element: (
          <Routes>
            <Route
              path="/room"
              element={
                <>
                  <MoonfallNavigationGuard session={session} />
                  <Link to="/next?tab=games">Next</Link>
                </>
              }
            />
            <Route path="/next" element={<h1>Next page</h1>} />
          </Routes>
        ),
      },
    ],
    { initialEntries: ['/room'] },
  )
  render(<RouterProvider router={router} />)
  await userEvent.click(screen.getByRole('link', { name: 'Next' }))
  expect(beforeLeave).toHaveBeenCalledOnce()
  expect(router.state.location.pathname).toBe('/room')
  resolve(true)
  await waitFor(() => expect(router.state.location.pathname).toBe('/next'))
  expect(router.state.location.search).toBe('?tab=games')
})

test('catalog query changes do not leave a mounted room', async () => {
  const session = { hasUnsaved: () => true, beforeLeave: vi.fn(async () => false) }
  const router = createMemoryRouter(
    [
      {
        path: '*',
        element: (
          <>
            <MoonfallNavigationGuard session={session} />
            <Link to="/vr?vr_compat=collection">Collection</Link>
          </>
        ),
      },
    ],
    { initialEntries: ['/vr?room=open'] },
  )
  render(<RouterProvider router={router} />)
  await userEvent.click(screen.getByRole('link', { name: 'Collection' }))
  expect(router.state.location.search).toBe('?vr_compat=collection')
  expect(session.beforeLeave).not.toHaveBeenCalled()
})

test('canceling a failed-save Back navigation keeps the room mounted', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  const session = { hasUnsaved: () => true, beforeLeave: vi.fn(async () => false) }
  const router = createMemoryRouter(
    [{ path: '*', element: <MoonfallNavigationGuard session={session} /> }],
    { initialEntries: ['/library', '/vr'], initialIndex: 1 },
  )
  const { unmount } = render(<RouterProvider router={router} />)
  await router.navigate(-1)
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce())
  expect(router.state.location.pathname).toBe('/vr')
  unmount()
  confirm.mockRestore()
})
