import { renderHook } from '@testing-library/react'
import { useTopBarReserve } from './useTopBarReserve'

test('shares the measured wrapped topbar height with body-portalled UI and removes it on unmount', () => {
  const shell = document.createElement('div')
  shell.className = 'od-shell'
  const header = document.createElement('header')
  shell.append(header)
  document.body.append(shell)

  let height = 76
  vi.spyOn(header, 'getBoundingClientRect').mockImplementation(() => ({ height }) as DOMRect)
  const ref = { current: header }
  const { unmount } = renderHook(() => useTopBarReserve(ref))

  expect(shell.style.getPropertyValue('--od-topbar-reserve-h')).toBe('76px')
  expect(document.body.style.getPropertyValue('--od-topbar-reserve-h')).toBe('76px')

  height = 92
  window.dispatchEvent(new Event('resize'))
  expect(document.body.style.getPropertyValue('--od-topbar-reserve-h')).toBe('92px')

  unmount()
  expect(shell.style.getPropertyValue('--od-topbar-reserve-h')).toBe('')
  expect(document.body.style.getPropertyValue('--od-topbar-reserve-h')).toBe('')
  shell.remove()
})
