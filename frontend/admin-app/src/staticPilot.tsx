import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Button, PageStatus, errorFromResponse } from '@oneirodex/ui'
import { App } from './App'
import './styles.css'

interface RuntimeBootstrap {
  csrf_token: string
  user: { id: string; name: string; role: string; avatar_url: string }
  theme: { name: string; era: string; icon_pack: string; stylesheets: string[]; scripts: string[] }
  preferences_url: string
}

function localUrl(value: string): string {
  const url = new URL(value, window.location.origin)
  if (url.origin !== window.location.origin) throw new Error('Runtime asset must be local.')
  return url.href
}

async function loadAsset(url: string, kind: 'style' | 'script') {
  const href = localUrl(url)
  // Retry reuses assets that finished loading; failed elements are removed below.
  const loaded = Array.from(document.querySelectorAll<HTMLElement>('[data-pilot-asset]')).find(
    (node) => node.dataset.pilotUrl === href && node.dataset.loaded === '1',
  )
  if (loaded) {
    if (kind === 'style') document.head.appendChild(loaded)
    return
  }
  await new Promise<void>((resolve, reject) => {
    const node =
      kind === 'style' ? document.createElement('link') : document.createElement('script')
    node.dataset.pilotAsset = kind
    node.dataset.pilotUrl = href
    if (node instanceof HTMLLinkElement) {
      node.rel = 'stylesheet'
      node.href = href
      const pathname = new URL(href).pathname
      if (pathname.endsWith('/icon-themes/previews.css')) node.id = 'od-icon-pack-previews-css'
      else if (pathname.includes('/icon-themes/') && pathname.endsWith('/pack.css'))
        node.id = 'od-icon-pack-css'
      else if (pathname.endsWith('/fonts.css') || pathname.endsWith('/theme_fonts.css'))
        node.id = 'od-theme-fonts-css'
    } else {
      node.src = href
      node.async = false
    }
    const failed = () => {
      clearTimeout(timeout)
      node.remove()
      reject(new Error('Unable to load the admin theme.'))
    }
    const timeout = window.setTimeout(failed, 15000)
    node.onload = () => {
      clearTimeout(timeout)
      node.dataset.loaded = '1'
      resolve()
    }
    node.onerror = failed
    document.head.appendChild(node)
  })
}

async function prepareRuntime() {
  const response = await fetch('/admin/api/runtime-bootstrap', {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
    cache: 'no-store',
  })
  if (!response.ok) throw await errorFromResponse(response, 'Load admin session')
  const data = (await response.json()) as RuntimeBootstrap
  if (
    !data.user?.id ||
    data.user.role !== 'admin' ||
    !data.csrf_token ||
    !data.theme?.name ||
    !Array.isArray(data.theme.stylesheets) ||
    !data.theme.stylesheets.length ||
    !Array.isArray(data.theme.scripts) ||
    !data.preferences_url
  ) {
    throw new Error('The admin runtime is not configured. Retry after it is available.')
  }
  const root = document.getElementById('admin-app-root')!
  root.dataset.username = data.user.name
  root.dataset.avatar = data.user.avatar_url || ''
  document.documentElement.dataset.theme = data.theme.name
  document.documentElement.dataset.era = data.theme.era
  document.documentElement.dataset.iconPack = data.theme.icon_pack
  document.documentElement.dataset.chrome = 'v2'
  const meta = document.createElement('meta')
  meta.name = 'csrf-token'
  meta.content = data.csrf_token
  document.head.querySelector('meta[name="csrf-token"]')?.remove()
  document.head.appendChild(meta)
  const preferences = document.createElement('script')
  preferences.type = 'application/json'
  preferences.id = 'od-prefs-panel-url'
  preferences.textContent = JSON.stringify(localUrl(data.preferences_url))
  document.getElementById(preferences.id)?.remove()
  document.body.appendChild(preferences)
  // Match base_admin: theme primitives precede app overrides; era scenery is last.
  const eraStyles = data.theme.stylesheets.filter((url) =>
    new URL(localUrl(url)).pathname.endsWith('/od-era.css'),
  )
  for (const url of data.theme.stylesheets.filter((url) => !eraStyles.includes(url)))
    await loadAsset(url, 'style')
  document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]').forEach((link) => {
    if (new URL(link.href).pathname.startsWith('/static/dist/admin-pilot/'))
      document.head.appendChild(link)
  })
  for (const url of eraStyles) await loadAsset(url, 'style')
  for (const url of data.theme.scripts) await loadAsset(url, 'script')
}

function StaticPilot() {
  const [attempt, setAttempt] = useState(0)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    setError('')
    prepareRuntime()
      .then(() => {
        if (active) setReady(true)
      })
      .catch((failure: unknown) => {
        if (active) setError(failure instanceof Error ? failure.message : 'Unable to load admin.')
      })
    return () => {
      active = false
    }
  }, [attempt])
  if (ready)
    return (
      <BrowserRouter>
        <App />
      </BrowserRouter>
    )
  return (
    <main className="od-admin-main" aria-busy={!error}>
      <section className="od-admin-card">
        <h1>Oneirodex Admin</h1>
        {error ? (
          <>
            <PageStatus announcement="alert">{error}</PageStatus>
            <Button type="button" onClick={() => setAttempt((value) => value + 1)}>
              Retry
            </Button>
            <a className="od-btn od-btn--ghost" href="/login">
              Sign in
            </a>
          </>
        ) : (
          <PageStatus announcement="status">Loading your admin session…</PageStatus>
        )}
      </section>
    </main>
  )
}

createRoot(document.getElementById('admin-app-root')!).render(<StaticPilot />)
