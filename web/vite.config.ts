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
    // The limit for a whole test is a plain timer, so seconds lost to the shared CI runner freezing this process count
    // against it, and the first test in a file also does the slow cold start. Only a test that hangs ever waits this long.
    testTimeout: 15000,
  },
})
