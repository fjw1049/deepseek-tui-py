import { createHash } from 'node:crypto'
import { readdirSync, readFileSync, writeFileSync, existsSync, statSync } from 'node:fs'
import { join, resolve } from 'path'
import type { Plugin } from 'vite'
import { defineConfig, externalizeDepsPlugin } from 'electron-vite'
import react from '@vitejs/plugin-react'

/**
 * Desktop is an iCloud File Provider folder on this machine. fileproviderd
 * periodically rewrites source files with identical bytes (mtime==ctime bump).
 * Vite/chokidar treat that as a change → HMR storm / `page reload` → UI kicks
 * back to the greeting screen. Seed content hashes at startup and swallow
 * hot updates whose bytes have not changed.
 */
function ignoreUnchangedContentPlugin(seedRoots: string[]): Plugin {
  const hashes = new Map<string, string>()
  const norm = (file: string): string => file.replace(/\\/g, '/')

  const hashFile = (file: string): string | null => {
    try {
      return createHash('sha1').update(readFileSync(file)).digest('hex')
    } catch {
      return null
    }
  }

  const seedDir = (dir: string): void => {
    if (!existsSync(dir)) return
    for (const name of readdirSync(dir)) {
      const full = join(dir, name)
      let st
      try {
        st = statSync(full)
      } catch {
        continue
      }
      if (st.isDirectory()) {
        if (name === 'node_modules' || name === 'out' || name === 'dist' || name === '.git') continue
        seedDir(full)
      } else if (st.isFile()) {
        const h = hashFile(full)
        if (h) hashes.set(norm(full), h)
      }
    }
  }

  return {
    name: 'workbench:ignore-unchanged-content',
    apply: 'serve',
    configureServer(server) {
      for (const root of seedRoots) seedDir(resolve(root))
      // Swallow at the watcher so full-reload paths (JSON, non-HMR .ts) never
      // reach the client. Only filter here — a second filter in handleHotUpdate
      // would see the already-updated hash and also drop real edits.
      const watcher = server.watcher
      const rawEmit = watcher.emit.bind(watcher)
      watcher.emit = ((event: string | symbol, ...args: unknown[]) => {
        if ((event === 'change' || event === 'add') && typeof args[0] === 'string') {
          const file = args[0]
          const key = norm(file)
          const next = hashFile(file)
          if (next !== null) {
            const prev = hashes.get(key)
            if (prev !== undefined && prev === next) return false
            hashes.set(key, next)
          }
        }
        return rawEmit(event, ...args)
      }) as typeof watcher.emit
    }
  }
}

/** Bundle Material Icon Theme SVGs so file chips do not depend on a glob into node_modules. */
function materialIconsPlugin(): Plugin {
  const virtualId = 'virtual:material-icons'
  const resolvedId = `\0${virtualId}`
  const iconsDir = resolve('node_modules/vscode-material-icons/generated/icons')

  return {
    name: 'workbench:material-icons',
    resolveId(id) {
      if (id === virtualId) return resolvedId
    },
    load(id) {
      if (id !== resolvedId) return
      if (!existsSync(iconsDir)) {
        return 'export const materialIconSvgByName = {}'
      }
      const files = readdirSync(iconsDir).filter((name) => name.endsWith('.svg'))
      const entries = files.map((file) => {
        const name = file.replace(/\.svg$/i, '')
        const svg = readFileSync(join(iconsDir, file), 'utf8')
        return `${JSON.stringify(name)}:${JSON.stringify(svg)}`
      })
      return `export const materialIconSvgByName = {${entries.join(',')}}`
    }
  }
}

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
    plugins: [
      externalizeDepsPlugin(),
      fixEsmShimPlugin(),
      ignoreUnchangedContentPlugin(['src/main', 'src/shared'])
    ]
  },
  preload: {
    plugins: [
      externalizeDepsPlugin(),
      ignoreUnchangedContentPlugin(['src/preload', 'src/shared'])
    ],
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
    // Pre-bundle deps that are only reachable through the lazily-loaded
    // StreamdownAssistant chunk. Without this, Vite discovers streamdown's
    // runtime imports (shiki/mermaid) on demand, re-runs the optimizer, and
    // invalidates the in-flight chunk hash -> "Failed to fetch dynamically
    // imported module" -> white screen when opening a chat.
    optimizeDeps: {
      include: [
        'streamdown',
        'shiki',
        'mermaid',
        'remark-gfm',
        'rehype-harden',
        'vscode-material-icons'
      ]
    },
    plugins: [
      react(),
      materialIconsPlugin(),
      ignoreUnchangedContentPlugin(['src/renderer/src', 'src/shared'])
    ],
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      // These files are not part of the running renderer graph (or always force
      // a full page reload). Watching them while another process edits the tree
      // kicks the UI back to the greeting screen on every touch.
      watch: {
        // macOS FSEvents also fires on inode/xattr (ctime) touches when content
        // and mtime are unchanged — Cursor indexing / Spotlight / provenance
        // scans were causing spurious `page reload` (e.g. resolve-channel-delivery).
        // Polling keys off mtime + size instead. Content-identical rewrites from
        // iCloud File Provider still bump mtime; ignoreUnchangedContentPlugin
        // swallows those via sha1.
        usePolling: true,
        interval: 1000,
        // FileProvider rewrites are often unlink+add; coalesce to one change so
        // the content-hash filter can drop the echo (atomic is off by default
        // when usePolling is true).
        atomic: 300,
        ignored: [
          '**/*.test.ts',
          '**/*.test.tsx',
          '**/*.d.ts',
          // Type-only modules — no runtime; Vite falls back to full page reload.
          '**/*-types.ts',
          '**/tsconfig*.json',
          '**/tailwind.config.js',
          '**/tailwind.config.cjs',
          // Build/cache trees — not part of the live renderer module graph.
          '**/node_modules/**',
          '**/out/**',
          '**/dist/**',
          '**/.git/**',
          '**/coverage/**'
        ]
      }
    }
  }
})
