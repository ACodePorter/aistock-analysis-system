
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    host: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        secure: false
      }
      ,
      // Proxy root-level endpoints used by the SPA in dev mode
      '/watchlist': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        secure: false
      },
      '/cache': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        secure: false
      }
    }
  }
})
