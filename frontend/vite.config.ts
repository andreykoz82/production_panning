import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// В разработке запросы /api проксируются на FastAPI (uvicorn на порту 8000)
const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  // vis-timeline (Гант) ~1 МБ, грузится отдельным чанком только на экране Ганта
  build: { chunkSizeWarningLimit: 1200 },
  server: { proxy: { '/api': apiTarget } },
  preview: { proxy: { '/api': apiTarget } },
})
