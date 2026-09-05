import { readFileSync } from 'node:fs'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

const packageMetadata = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf8'),
) as { version: string }

export default defineConfig({
  define: {
    __APP_VERSION__: JSON.stringify(packageMetadata.version),
  },
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: [
        'images/family-car-agent-logo.png',
        'icons/family-car-agent-192.png',
        'icons/family-car-agent-512.png',
        'icons/family-car-agent-apple-touch-180.png',
      ],
      manifest: {
        name: 'Family Car Agent',
        short_name: 'Family Car',
        description: 'ניהול חכם של הרכב המשפחתי המשותף',
        lang: 'he',
        dir: 'rtl',
        start_url: '/',
        display: 'standalone',
        background_color: '#fffefc',
        theme_color: '#fffefc',
        icons: [
          {
            src: '/icons/family-car-agent-192.png',
            sizes: '192x192',
            type: 'image/png',
            purpose: 'any',
          },
          {
            src: '/icons/family-car-agent-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'any',
          },
        ],
      },
    }),
  ],
})
