import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发期把 /api 和 /healthz 代理到本地 FastAPI（8000），避免跨域。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8000',
      '/healthz': 'http://localhost:8000',
    },
  },
  build: { outDir: 'dist' },
})
