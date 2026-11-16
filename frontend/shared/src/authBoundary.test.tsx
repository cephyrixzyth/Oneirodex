import { act, cleanup, render, screen } from '@testing-library/react'
import { useEffect, useState } from 'react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { ViewerProvider } from './ViewerContext.js'
import { signIn, signOut } from './authApi.js'
import { readAuthBoundaryEpoch, subscribeAuthBoundary } from './authBoundary.js'

const KEY = 'od.auth.boundary.v1'
const EVENT = 'od-auth-boundary'
class TestChannel {
  static instances: TestChannel[] = []
  closed = false
  listeners = new Set<(event: MessageEvent) => void>()
  constructor() {
    TestChannel.instances.push(this)
  }
  addEventListener(_type: string, listener: (event: MessageEvent) => void) {
    this.listeners.add(listener)
  }
  removeEventListener(_type: string, listener: (event: MessageEvent) => void) {
    this.listeners.delete(listener)
  }
  postMessage(data: unknown) {
    for (const channel of TestChannel.instances)
      if (channel !== this && !channel.closed) channel.emit(data)
  }
  emit(data: unknown) {
    for (const listener of this.listeners) listener(new MessageEvent('message', { data }))
  }
  close() {
    this.closed = true
  }
}
beforeEach(() => {
  TestChannel.instances = []
  localStorage.clear()
  document.head.innerHTML = '<meta name="csrf-token" content="synthetic-csrf">'
})
afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  localStorage.clear()
})

test('successful actual logout publishes a non-personal boundary for other documents', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
  const observed = vi.fn()
  window.addEventListener(EVENT, observed)
  try {
    await signOut()
    expect(localStorage.getItem(KEY)).toBeTruthy()
    expect(observed).toHaveBeenCalledOnce()
    expect(localStorage.getItem(KEY)).not.toContain('user')
  } finally {
    window.removeEventListener(EVENT, observed)
  }
})

test('same-document session boundary removes the entire prior private view', () => {
  render(
    <ViewerProvider value={{ userId: 7, role: 'admin' }}>
      <div>PRIOR_PRIVATE_VIEW</div>
    </ViewerProvider>,
  )
  act(() => window.dispatchEvent(new Event(EVENT)))
  expect(screen.queryByText('PRIOR_PRIVATE_VIEW')).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: /sign in/i })).toHaveAttribute('href', '/login')
})

test('a cross-tab boundary prevents a late prior-identity response from rendering', async () => {
  let finish!: (name: string) => void
  const delayed = new Promise<string>((resolve) => {
    finish = resolve
  })
  function PrivateView() {
    const [name, setName] = useState('Loading synthetic private data')
    useEffect(() => {
      delayed.then(setName)
    }, [])
    return <div>{name}</div>
  }
  render(
    <ViewerProvider value={{ userId: 7 }}>
      <PrivateView />
    </ViewerProvider>,
  )
  act(() => {
    localStorage.setItem(KEY, '11111111-1111-4111-8111-111111111111')
    window.dispatchEvent(
      new StorageEvent('storage', {
        key: KEY,
        newValue: localStorage.getItem(KEY),
        storageArea: localStorage,
      }),
    )
  })
  await act(async () => {
    finish('PRIOR_PRIVATE_RESULT')
    await delayed
  })
  expect(screen.queryByText('PRIOR_PRIVATE_RESULT')).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: /sign in/i })).toBeInTheDocument()
})

test('current-viewer results still render without a session boundary', async () => {
  let finish!: (name: string) => void
  const delayed = new Promise<string>((resolve) => {
    finish = resolve
  })
  function PrivateView() {
    const [name, setName] = useState('Loading')
    useEffect(() => {
      delayed.then(setName)
    }, [])
    return <div>{name}</div>
  }
  render(
    <ViewerProvider value={{ userId: 7 }}>
      <PrivateView />
    </ViewerProvider>,
  )
  await act(async () => {
    finish('CURRENT_PRIVATE_RESULT')
    await delayed
  })
  expect(screen.getByText('CURRENT_PRIVATE_RESULT')).toBeInTheDocument()
})

test('a rejected logout does not publish a false successful sign-out boundary', async () => {
  const original = '11111111-1111-4111-8111-111111111111'
  localStorage.setItem(KEY, original)
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(new Response('{"message":"Denied"}', { status: 403 })),
  )
  const observed = vi.fn()
  window.addEventListener(EVENT, observed)
  try {
    await expect(signOut()).rejects.toBeTruthy()
    expect(localStorage.getItem(KEY)).toBe(original)
    expect(observed).not.toHaveBeenCalled()
  } finally {
    window.removeEventListener(EVENT, observed)
  }
})

test('unrelated storage updates do not hide the signed-in view', () => {
  render(
    <ViewerProvider value={{ userId: 7 }}>
      <div>CURRENT_PRIVATE_VIEW</div>
    </ViewerProvider>,
  )
  act(() =>
    window.dispatchEvent(new StorageEvent('storage', { key: 'od.theme', newValue: 'dark-green' })),
  )
  expect(screen.getByText('CURRENT_PRIVATE_VIEW')).toBeInTheDocument()
})

test('BroadcastChannel removes the private view when storage is blocked', () => {
  vi.stubGlobal('BroadcastChannel', TestChannel)
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new DOMException('Blocked', 'SecurityError')
  })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new DOMException('Blocked', 'SecurityError')
  })
  render(
    <ViewerProvider value={{ userId: 7 }}>
      <div>PRIVATE_WITHOUT_STORAGE</div>
    </ViewerProvider>,
  )
  const channel = TestChannel.instances[0]
  act(() => channel.emit({ type: 'session-ended', epoch: 'opaque-remote-epoch' }))
  expect(screen.queryByText('PRIVATE_WITHOUT_STORAGE')).not.toBeInTheDocument()
  expect(channel.closed).toBe(true)
  expect(channel.listeners.size).toBe(0)
})

test('no available cross-tab channel fails closed when the private page loses focus', () => {
  vi.stubGlobal('BroadcastChannel', undefined)
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new DOMException('Blocked', 'SecurityError')
  })
  render(
    <ViewerProvider value={{ userId: 7 }}>
      <div>PRIVATE_UNTIL_BLUR</div>
    </ViewerProvider>,
  )
  expect(screen.getByText('PRIVATE_UNTIL_BLUR')).toBeInTheDocument()
  act(() => window.dispatchEvent(new Event('blur')))
  expect(screen.queryByText('PRIVATE_UNTIL_BLUR')).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: /sign in/i })).toHaveAttribute('href', '/login')
})

test('focus detects a missed storage notification without reusing old private state', () => {
  render(
    <ViewerProvider value={{ userId: 7 }}>
      <div>PRIVATE_BEFORE_MISSED_EVENT</div>
    </ViewerProvider>,
  )
  localStorage.setItem(KEY, 'new-opaque-epoch')
  act(() => window.dispatchEvent(new Event('focus')))
  expect(screen.queryByText('PRIVATE_BEFORE_MISSED_EVENT')).not.toBeInTheDocument()
})

test('an opaque old storage event does not invalidate a fresh page with the current epoch', () => {
  localStorage.setItem(KEY, 'current-opaque-epoch')
  render(
    <ViewerProvider value={{ userId: 8 }}>
      <div>NEW_PRIVATE_VIEW</div>
    </ViewerProvider>,
  )
  act(() =>
    window.dispatchEvent(new StorageEvent('storage', { key: KEY, newValue: 'older-epoch' })),
  )
  expect(screen.getByText('NEW_PRIVATE_VIEW')).toBeInTheDocument()
})

test('malformed channel payloads are ignored and a valid signal still retires the view', () => {
  vi.stubGlobal('BroadcastChannel', TestChannel)
  render(
    <ViewerProvider value={{ userId: 7 }}>
      <div>PRIVATE_VALIDATION_CONTROL</div>
    </ViewerProvider>,
  )
  const channel = TestChannel.instances[0]
  act(() => {
    for (const data of [
      null,
      'session-ended',
      {},
      { type: 'other', epoch: 'new' },
      { type: 'session-ended', epoch: 7 },
      { type: 'session-ended', epoch: '' },
      { type: 'session-ended', epoch: 'x'.repeat(257) },
    ])
      channel.emit(data)
  })
  expect(screen.getByText('PRIVATE_VALIDATION_CONTROL')).toBeInTheDocument()
  act(() => channel.emit({ type: 'session-ended', epoch: 'valid-opaque-epoch' }))
  expect(screen.queryByText('PRIVATE_VALIDATION_CONTROL')).not.toBeInTheDocument()
})

test('unsubscribing releases channels and stops local and remote callbacks', () => {
  vi.stubGlobal('BroadcastChannel', TestChannel)
  const ended = vi.fn()
  const unsubscribe = subscribeAuthBoundary(ended, readAuthBoundaryEpoch())
  const channel = TestChannel.instances[0]
  unsubscribe()
  localStorage.setItem(KEY, 'later-epoch')
  window.dispatchEvent(new Event(EVENT))
  window.dispatchEvent(new StorageEvent('storage', { key: KEY, newValue: 'later-epoch' }))
  channel.emit({ type: 'session-ended', epoch: 'later-epoch' })
  expect(ended).not.toHaveBeenCalled()
  expect(channel.closed).toBe(true)
  expect(channel.listeners.size).toBe(0)
})

test('successful local logout still clears private UI when both optional channels fail', async () => {
  vi.stubGlobal('BroadcastChannel', undefined)
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
    throw new DOMException('Blocked', 'SecurityError')
  })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
  render(
    <ViewerProvider value={{ userId: 7 }}>
      <div>LOCAL_PRIVATE_VIEW</div>
    </ViewerProvider>,
  )
  await act(async () => {
    await signOut()
  })
  expect(screen.queryByText('LOCAL_PRIVATE_VIEW')).not.toBeInTheDocument()
})

test('repeated logout epochs are distinct without storing identity data', async () => {
  vi.spyOn(Date, 'now').mockReturnValue(1)
  vi.spyOn(window.crypto, 'getRandomValues').mockImplementation(() => {
    throw new Error('Unavailable')
  })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }))
  await signOut()
  const first = localStorage.getItem(KEY)
  await signOut()
  expect(localStorage.getItem(KEY)).not.toBe(first)
  expect(Object.keys(localStorage)).toEqual([KEY])
})

test('a restored document with unavailable storage requires a fresh sign-in check', () => {
  vi.stubGlobal('BroadcastChannel', TestChannel)
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
    throw new DOMException('Blocked', 'SecurityError')
  })
  render(
    <ViewerProvider value={{ userId: 7 }}>
      <div>PRIVATE_RESTORED_DOCUMENT</div>
    </ViewerProvider>,
  )
  act(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })))
  expect(screen.queryByText('PRIVATE_RESTORED_DOCUMENT')).not.toBeInTheDocument()
})

test('confirmed sign-in retires old private documents even without a prior logout reply', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: async () => ({ next_url: '/library' }) }),
  )
  render(
    <ViewerProvider value={{ userId: 7 }}>
      <div>PRIOR_VIEW_WITH_LOST_LOGOUT_REPLY</div>
    </ViewerProvider>,
  )
  await act(async () => {
    await expect(
      signIn({ username: 'synthetic-next-account', password: 'synthetic' }),
    ).resolves.toEqual({ next_url: '/library' })
  })
  expect(screen.queryByText('PRIOR_VIEW_WITH_LOST_LOGOUT_REPLY')).not.toBeInTheDocument()
  expect(localStorage.getItem(KEY)).toBeTruthy()
})
