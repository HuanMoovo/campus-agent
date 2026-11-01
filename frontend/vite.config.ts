import { readFileSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'

const root = fileURLToPath(new URL('.', import.meta.url))
const { version } = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8')) as { version: string }

/**
 * Include the release and actual build content in cache names so same-version UI/icon
 * updates also refresh the worker. HTML remains network-first; obsolete app caches
 * are removed on activation without touching other applications' caches.
 */
function serviceWorkerVersion(): Plugin {
  let outputDirectory: string
  return {
    name: 'mens-service-worker-version',
    apply: 'build',
    configResolved(config) {
      outputDirectory = resolve(config.root, config.build.outDir)
    },
    closeBundle() {
      const file = resolve(outputDirectory, 'sw.js')
      const source = readFileSync(file, 'utf8')
      if (!source.includes('__MENS_VERSION__')) {
        throw new Error(`${file} is missing the __MENS_VERSION__ placeholder`)
      }
      const fingerprint = createHash('sha256')
        .update(readFileSync(resolve(outputDirectory, 'index.html')))
        .update(readFileSync(resolve(outputDirectory, 'favicon.png')))
        .digest('hex').slice(0, 12)
      writeFileSync(file, source.replaceAll('__MENS_VERSION__', `${version}-${fingerprint}`))
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
