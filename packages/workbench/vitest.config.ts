import { resolve } from 'node:path'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  resolve: {
    alias: {
      '@shared': resolve(__dirname, 'src/shared'),
      // electron-vite bundles the real icons via materialIconsPlugin(); tests
      // only need the module to resolve (FileKindIcon has a generic fallback).
      'virtual:material-icons': resolve(__dirname, 'src/renderer/src/test/material-icons-stub.ts')
    }
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts']
  }
})
