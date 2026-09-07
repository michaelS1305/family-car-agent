import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { AuthProvider } from './auth/AuthContext.tsx'
import { AppPreferencesProvider } from './preferences/AppPreferencesContext.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppPreferencesProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </AppPreferencesProvider>
  </StrictMode>,
)
