import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    https: false,
    proxy: {
      '/ws': {
        target: 'wss://localhost:8000',
        ws: true,
        secure: false,
      },
    },
  },
  build: {
    outDir: 'dist',
  },
})
