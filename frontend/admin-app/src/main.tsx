import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { AdminTabs } from './components/AdminTabs'
import { App } from './App'
import { AppErrorBoundary, AuthSessionBoundary } from '@oneirodex/ui'
import { ImportLeafLibraries } from './components/ImportLeafLibraries'
import { ProposeLeafLibraries } from './components/ProposeLeafLibraries'
import './styles.css'

const root = document.getElementById('admin-app-root')
if (root) {
  createRoot(root).render(
    <AuthSessionBoundary>
      <BrowserRouter>
        <AppErrorBoundary>
          <App />
        </AppErrorBoundary>
      </BrowserRouter>
    </AuthSessionBoundary>,
  )
}

// Hybrid Jinja surfaces (e.g. Library tools → Propose leaf tab) mount the
// same confirm UI beside legacy content when App skips the SPA main.
const proposeLeafMount = document.getElementById('propose-leaf-mount')
if (proposeLeafMount && !proposeLeafMount.dataset.reactMounted) {
  proposeLeafMount.dataset.reactMounted = '1'
  createRoot(proposeLeafMount).render(<ProposeLeafLibraries />)
}

const importLeafMount = document.getElementById('import-leaf-mount')
if (importLeafMount && !importLeafMount.dataset.reactMounted) {
  importLeafMount.dataset.reactMounted = '1'
  createRoot(importLeafMount).render(<ImportLeafLibraries />)
}

// Any legacy page can group its panels into tabs by marking them up and
// dropping a mount in: the tab bar is React, the panels stay server-rendered
// and keep posting to the handler they always did.
document.querySelectorAll('[data-od-tabs-mount]').forEach((node) => {
  const mount = node as HTMLElement
  if (mount.dataset.reactMounted) return
  const container = mount.closest('[data-od-tabs]') || document
  mount.dataset.reactMounted = '1'
  createRoot(mount).render(<AdminTabs container={container} />)
})
