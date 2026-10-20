import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

const backendPort = process.env.HOMESTART_PORT ?? '8000'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    // During development the Vite server forwards API calls to the backend (port 8000, or HOMESTART_PORT
    // when the development backend runs next to an installed one).
    proxy: {
      '/api': `http://127.0.0.1:${backendPort}`,
      '/ws': { target: `ws://127.0.0.1:${backendPort}`, ws: true },
    },
  },
})
