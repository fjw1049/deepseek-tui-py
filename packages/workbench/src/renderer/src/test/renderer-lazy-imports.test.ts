import { mkdtemp, rm } from 'node:fs/promises'
import { resolve } from 'node:path'
import { init, parse } from 'es-module-lexer'
import { createServer, loadConfigFromFile, type InlineConfig } from 'vite'
import { expect, it } from 'vitest'

it('serves lazy workbench pages and their dependencies with a fresh Vite cache', async () => {
  await init
  const loaded = await loadConfigFromFile(
    { command: 'serve', mode: 'development' },
    resolve('electron.vite.config.ts')
  )
  const renderer = (loaded!.config as { renderer: InlineConfig }).renderer
  const cacheDir = await mkdtemp(resolve('node_modules/.vite-lazy-imports-'))
  const server = await createServer({
    ...renderer,
    configFile: false,
    root: resolve('src/renderer'),
    cacheDir,
    server: { host: '127.0.0.1', port: 5199, strictPort: false, hmr: false }
  })
  try {
    await server.listen()
    const address = server.httpServer!.address()
    if (!address || typeof address === 'string') throw new Error('Missing test server address')
    const origin = `http://127.0.0.1:${address.port}`
    const seen = new Set<string>()
    const queue = ['/src/components/Workbench.tsx']
    const failures: string[] = []
    while (queue.length) {
      const batch = [...new Set(queue.splice(0, 24))].filter((url) => !seen.has(url))
      batch.forEach((url) => seen.add(url))
      await Promise.all(batch.map(async (url) => {
        const response = await fetch(origin + url)
        const source = await response.text()
        if (!response.ok) {
          failures.push(`${response.status} ${url}`)
          return
        }
        if (!response.headers.get('content-type')?.includes('javascript')) return
        for (const imported of parse(source)[0]) {
          // Follow static dependencies and application lazy imports; library
          // dynamic imports include hundreds of optional language grammars.
          if (imported.n?.startsWith('/') && (imported.d === -1 || imported.n.startsWith('/src/'))) {
            queue.push(imported.n)
          }
        }
      }))
    }
    expect(failures).toEqual([])
    for (const dependency of ['qrcode', 'd3-dsv', '@monaco-editor_react', 'monaco-editor']) {
      expect([...seen].some((url) => url.includes(`/deps/${dependency}.js?`)), dependency).toBe(true)
    }
  } finally {
    await server.close()
    await rm(cacheDir, { recursive: true, force: true })
  }
}, 60_000)
