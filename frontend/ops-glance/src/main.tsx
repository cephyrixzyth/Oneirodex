import { createRoot } from 'react-dom/client'
import { OpsApp } from './OpsApp'
import { AuthSessionBoundary } from '@oneirodex/ui'
/* Local CSS so Docker Node stage can build without the Flask theme tree. */
import './ops-glance.css'

const rootElement = document.getElementById('ops-glance-root')
if (rootElement) {
  const pollMs = Number.parseInt(rootElement.dataset.pollMs ?? '', 10)

  createRoot(rootElement).render(
    <AuthSessionBoundary>
      <OpsApp pollMs={Number.isFinite(pollMs) && pollMs > 0 ? pollMs : 15000} />
    </AuthSessionBoundary>,
  )
}
