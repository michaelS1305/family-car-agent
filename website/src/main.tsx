import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'
import { updateLegacyWorker } from './legacyWorker'

if ('serviceWorker' in navigator) void updateLegacyWorker(navigator.serviceWorker, window.location.origin)

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
