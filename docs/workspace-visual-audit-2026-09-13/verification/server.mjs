// Run from packages/workbench: node ../../docs/workspace-visual-audit-2026-09-13/verification/server.mjs
import fs from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'
const base = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')
const pkg = base + '/packages/workbench'
const { build, preview } = await import(pkg + '/node_modules/vite/dist/node/index.js')
const { default: react } = await import(pkg + '/node_modules/@vitejs/plugin-react/dist/index.js')
const { default: tailwind } = await import(pkg + '/node_modules/tailwindcss/lib/index.js')
const { default: autoprefixer } = await import(pkg + '/node_modules/autoprefixer/lib/autoprefixer.js')
const outDir = resolve(tmpdir(), 'workspace-verification-dist')
await build({
  configFile: false,
  root: base,
  base: '/',
  resolve: {
    dedupe: ['react', 'react-dom'],
    alias: Object.fromEntries([
      ['@shared', pkg + '/src/shared'],
      ...['react', 'react-dom', 'react-i18next', 'i18next', 'monaco-editor'].map(name => [name, pkg + '/node_modules/' + name])
    ])
  },
  plugins: [react(), {
    name: 'verification-icons',
    resolveId(id) { if (id === 'virtual:material-icons') return '\0icons' },
    load(id) {
      if (id !== '\0icons') return
      const dir = pkg + '/node_modules/vscode-material-icons/generated/icons'
      const icons = Object.fromEntries(fs.readdirSync(dir).filter(f => f.endsWith('.svg')).map(f => [f.slice(0, -4), fs.readFileSync(dir + '/' + f, 'utf8')]))
      return 'export const materialIconSvgByName=' + JSON.stringify(icons)
    }
  }],
  css: { postcss: { plugins: [tailwind({ config: pkg + '/tailwind.config.js' }), autoprefixer()] } },
  build: { target: 'esnext', outDir, emptyOutDir: true, rollupOptions: { input: base + '/docs/workspace-visual-audit-2026-09-13/verification/index.html' } }
})
await preview({ configFile: false, root: base, build: { outDir }, preview: { host: '127.0.0.1', port: 5188, strictPort: true } })
console.log('Verification ready on http://127.0.0.1:5188/docs/workspace-visual-audit-2026-09-13/verification/')
