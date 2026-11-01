import path from 'node:path'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Read VITE_* variables from the single .env file at the repository root.
  envDir: '..',
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // The flows that chain several awaited steps need headroom on a slow, shared CI runner,
    // where the default 5s is not enough and the whole test times out.
    testTimeout: 15000,
  },
})
