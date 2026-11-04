import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'
import { readFileSync } from 'node:fs'
import { Agent } from 'node:https'

// https://vite.dev/config/
export default defineConfig(({ command }) => {
  const tls = command === 'serve' ? {
    cert: readFileSync(new URL('../data/security/server.crt', import.meta.url)),
    key: readFileSync(new URL('../data/security/server.key', import.meta.url))
  } : undefined
  return {
  plugins: [
    vue(),
    vueDevTools(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
  server: {
    host: '127.0.0.1',
    https: tls,
    proxy: {
      '/api': {
        target: 'https://localhost:8443',
        changeOrigin: false,
        agent: tls ? new Agent({ ca: tls.cert }) : undefined,
        secure: true
      }
    }
  }
  }
})
