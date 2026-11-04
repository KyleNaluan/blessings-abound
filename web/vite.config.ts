import path from 'node:path'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'

import { checkNoServerSecrets } from './viteEnvCheck.ts'

// Every VITE_ value is built into the public JavaScript, so a server secret stops the build.
checkNoServerSecrets(loadEnv(process.env.NODE_ENV ?? 'development', '..', ''))

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
    // Vitest's limit for a whole test is a plain timer, so a freeze of the shared CI runner counts against it.
    // The runner sets the limit instead, counting only the time this process ran.
    runner: './src/test/runner.ts',
    testTimeout: 0,
  },
})
