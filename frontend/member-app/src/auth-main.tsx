import { createRoot } from 'react-dom/client'
import { AuthApp } from './AuthApp'
import './auth-pilot.css'

const root = document.getElementById('member-auth-root')
if (root) createRoot(root).render(<AuthApp />)
