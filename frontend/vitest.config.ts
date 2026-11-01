import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  test: {
    environment: 'happy-dom',
    include: ['tests/**/*.test.ts'],
    // Give full-app DOM checks a stable CPU budget on hosted CI runners.
    fileParallelism: !process.env.CI,
  },
})
