
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    host: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8090',
        changeOrigin: true,
        secure: false
      },
      // Proxy root-level endpoints used by the SPA in dev mode
      '/watchlist': {
        target: 'http://127.0.0.1:8090',
        changeOrigin: true,
        secure: false
      },
      '/cache': {
        target: 'http://127.0.0.1:8090',
        changeOrigin: true,
        secure: false
      },
      '/search_stock': {
        target: 'http://127.0.0.1:8090',
        changeOrigin: true,
        secure: false
      },
      '/run': {
        target: 'http://127.0.0.1:8090',
        changeOrigin: true,
        secure: false
      },
      '/report': {
        target: 'http://127.0.0.1:8090',
        changeOrigin: true,
        secure: false
      }
    }
  }
})
