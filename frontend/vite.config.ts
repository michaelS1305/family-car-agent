import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['images/family-car-agent-logo.png'],
      manifest: {
        name: 'Family Car Agent',
        short_name: 'Family Car',
        description: 'ניהול חכם של הרכב המשפחתי המשותף',
        lang: 'he',
        dir: 'rtl',
        start_url: '/',
        display: 'standalone',
        background_color: '#f7faf8',
        theme_color: '#28705c',
        icons: [
          {
            src: '/images/family-car-agent-logo.png',
            sizes: '1254x1254',
            type: 'image/png',
            purpose: 'any',
          },
        ],
      },
    }),
  ],
})
