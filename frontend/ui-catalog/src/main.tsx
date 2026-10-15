import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import '../../../oneirodex/setup/default_theme/css/od-tokens.css'
import '../../../oneirodex/setup/default_theme/css/od-primitives.css'
import './style.css'

const root = document.getElementById('root')
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}
