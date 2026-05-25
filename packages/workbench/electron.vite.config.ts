import { resolve } from 'path'
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import type { Plugin } from 'vite'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'

/** electron-vite inserts `import __cjs_mod__ from 'node:module'` which breaks with external zod v4. */
function fixEsmShimPlugin(): Plugin {
  const brokenShim =
    /import __cjs_mod__ from ["']node:module["'];\nconst __filename = import\.meta\.filename;\nconst __dirname = import\.meta\.dirname;\nconst (\w+) = __cjs_mod__\.createRequire\(import\.meta\.url\);/g
  const fixedShim = `import { createRequire } from "node:module";
const __filename = import.meta.filename;
const __dirname = import.meta.dirname;
const $1 = createRequire(import.meta.url);`

  return {
    name: 'workbench:fix-esm-shim',
    apply: 'build',
    enforce: 'post',
    closeBundle() {
      const mainFile = resolve('out/main/index.js')
      if (!existsSync(mainFile)) return
      const code = readFileSync(mainFile, 'utf8')
      if (!brokenShim.test(code)) return
      brokenShim.lastIndex = 0
      writeFileSync(mainFile, code.replace(brokenShim, fixedShim))
    }
  }
}

export default defineConfig({
  main: {
    plugins: [externalizeDepsPlugin(), fixEsmShimPlugin()]
  },
  preload: {
    plugins: [externalizeDepsPlugin()],
    build: {
      rollupOptions: {
        output: {
          format: 'cjs',
          entryFileNames: '[name].cjs'
        }
      }
    }
  },
  renderer: {
    resolve: {
      alias: {
        '@renderer': resolve('src/renderer/src'),
        '@shared': resolve('src/shared')
      }
    },
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true
    }
  }
})
