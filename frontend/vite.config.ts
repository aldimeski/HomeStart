import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    // During development the Vite server forwards API calls to the backend on port 8000.
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
