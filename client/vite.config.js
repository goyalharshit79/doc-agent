import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',   // listen on all interfaces (Tailscale, Wi-Fi, etc.)
  },
  optimizeDeps: {
    include: ['pdfjs-dist']
  }
})
