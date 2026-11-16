import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// В разработке запросы /api проксируются на FastAPI (uvicorn на порту 8000)
const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': apiTarget } },
  preview: { proxy: { '/api': apiTarget } },
})
