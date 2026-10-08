import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'

const root = fileURLToPath(new URL('.', import.meta.url))
const { version } = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8')) as { version: string }

/**
 * The offline shell caches its own name, so a released build must use a fresh cache key or
 * installed copies keep serving the previous shell. The version comes from package.json rather
 * than a hand-maintained string, and the build fails loudly if the placeholder disappears.
 */
function serviceWorkerVersion(): Plugin {
  return {
    name: 'mens-service-worker-version',
    apply: 'build',
    closeBundle() {
      const file = resolve(root, 'dist', 'sw.js')
      const source = readFileSync(file, 'utf8')
      if (!source.includes('__MENS_VERSION__')) {
        throw new Error('dist/sw.js is missing the __MENS_VERSION__ placeholder')
      }
      writeFileSync(file, source.replaceAll('__MENS_VERSION__', version))
    },
  }
}

export default defineConfig({
  plugins: [vue(), serviceWorkerVersion()],
  build: {
    // The UI kit is one large, rarely changing vendor file; keep it separate so the
    // application chunk stays small and the vendor file caches across releases.
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // Vite 8's type checks reject the object form of manualChunks; the function form keeps the
        // same split: the UI kit apart from the Vue runtime stack, everything else default.
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('element-plus')) return 'vendor-element'
          if (id.includes('/node_modules/vue/') || id.includes('/node_modules/@vue/') || id.includes('/node_modules/pinia/')) return 'vendor-vue'
        },
      },
    },
  },
  preview: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
