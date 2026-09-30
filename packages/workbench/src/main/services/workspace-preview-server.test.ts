import { mkdtemp, writeFile, rm, symlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { get } from 'node:http'
import { afterEach, describe, expect, it } from 'vitest'
import { isHtmlPreviewPath } from '../../shared/html-preview'
import { isImagePreviewPath } from '../../shared/image-preview'
import {
  getWorkspacePreviewUrl,
  ensureWorkspacePreviewServer,
  shutdownWorkspacePreviewServers
} from './workspace-preview-server'

describe('isHtmlPreviewPath', () => {
  it('accepts html extensions', () => {
    expect(isHtmlPreviewPath('/tmp/a.html')).toBe(true)
    expect(isHtmlPreviewPath('reports/dashboard.HTML')).toBe(true)
    expect(isHtmlPreviewPath('x.htm')).toBe(true)
  })

  it('rejects non-html paths', () => {
    expect(isHtmlPreviewPath('/tmp/a.py')).toBe(false)
    expect(isHtmlPreviewPath('/tmp/a.html.bak')).toBe(false)
    expect(isHtmlPreviewPath('')).toBe(false)
  })
})

describe('isImagePreviewPath', () => {
  it('accepts common image extensions', () => {
    expect(isImagePreviewPath('/tmp/a.png')).toBe(true)
    expect(isImagePreviewPath('shots/photo.JPG')).toBe(true)
    expect(isImagePreviewPath('icon.webp')).toBe(true)
    expect(isImagePreviewPath('diagram.SVG')).toBe(true)
  })

  it('rejects non-image paths', () => {
    expect(isImagePreviewPath('/tmp/a.py')).toBe(false)
    expect(isImagePreviewPath('/tmp/a.png.bak')).toBe(false)
    expect(isImagePreviewPath('')).toBe(false)
  })
})

describe('getWorkspacePreviewUrl', () => {
  const dirs: string[] = []

  afterEach(async () => {
    await shutdownWorkspacePreviewServers()
    await Promise.all(dirs.splice(0).map((dir) => rm(dir, { recursive: true, force: true })))
  })

  it('shares one server between concurrent requests for the same workspace', async () => {
    const root = await mkdtemp(join(tmpdir(), 'ds-preview-concurrent-'))
    dirs.push(root)
    const entries = await Promise.all(
      Array.from({ length: 4 }, () => ensureWorkspacePreviewServer(root))
    )
    expect(new Set(entries.map((entry) => entry.port)).size).toBe(1)
    // Close all entries even when this regression fails on the old code.
    await Promise.all(entries.map((entry) => new Promise<void>((done) => entry.server.close(() => done()))))
  })

  it('blocks symlinks escaping the workspace and hidden workspace files', async () => {
    const root = await mkdtemp(join(tmpdir(), 'ds-preview-boundary-'))
    const outside = await mkdtemp(join(tmpdir(), 'ds-preview-outside-'))
    dirs.push(root, outside)
    await writeFile(join(root, 'index.html'), '<html>ok</html>')
    await writeFile(join(root, '.env'), 'PRIVATE_KEY=secret')
    await writeFile(join(outside, 'secret.txt'), 'outside secret')
    await symlink(join(outside, 'secret.txt'), join(root, 'linked.txt'))
    const result = await getWorkspacePreviewUrl({ path: 'index.html', workspaceRoot: root })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    for (const path of ['linked.txt', '.env']) {
      const response = await fetch(new URL(path, result.url))
      expect(response.status, path).toBe(404)
      expect(await response.text()).not.toContain('secret')
    }
  })

  it('still serves symlinked assets inside the workspace using their URL extension', async () => {
    const root = await mkdtemp(join(tmpdir(), 'ds-preview-assets-'))
    dirs.push(root)
    await writeFile(join(root, 'index.html'), '<html>ok</html>')
    await writeFile(join(root, 'styles.txt'), 'body { color: red; }')
    await symlink(join(root, 'styles.txt'), join(root, 'styles.css'))
    const result = await getWorkspacePreviewUrl({ path: 'index.html', workspaceRoot: root })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    const response = await fetch(new URL('styles.css', result.url))
    expect(response.headers.get('content-type')).toBe('text/css; charset=utf-8')
    expect(await response.text()).toContain('color: red')
  })

  it('rejects foreign Host headers, invalid paths and unsupported methods', async () => {
    const root = await mkdtemp(join(tmpdir(), 'ds-preview-http-'))
    dirs.push(root)
    await writeFile(join(root, 'index.html'), 'ok')
    const result = await getWorkspacePreviewUrl({ path: 'index.html', workspaceRoot: root })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    // fetch rewrites Host; use HTTP directly to exercise DNS-rebinding checks.
    const foreignHostStatus = await new Promise<number | undefined>((resolve, reject) => {
      get(result.url, { headers: { Host: 'attacker.example' } }, (response) => {
        response.resume()
        resolve(response.statusCode)
      }).on('error', reject)
    })
    expect(foreignHostStatus).toBe(403)
    expect((await fetch(new URL('/%ZZ', result.url))).status).toBe(400)
    expect((await fetch(result.url, { method: 'POST' })).status).toBe(405)
    const head = await fetch(result.url, { method: 'HEAD' })
    expect(head.status).toBe(200)
    expect(head.headers.get('content-length')).toBe('2')
    expect(await head.text()).toBe('')
  })

  it('serves PDF bytes with the native viewer content type', async () => {
    const root = await mkdtemp(join(tmpdir(), 'ds-pdf-preview-'))
    dirs.push(root)
    const bytes = Buffer.from('%PDF-1.4\n% fixture\n')
    await writeFile(join(root, 'report.PDF'), bytes)
    const result = await getWorkspacePreviewUrl({ path: 'report.PDF', workspaceRoot: root })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    const response = await fetch(result.url)
    expect(response.headers.get('content-type')).toBe('application/pdf')
    expect(Buffer.from(await response.arrayBuffer())).toEqual(bytes)
  })

  it('serves an html file inside the workspace over localhost', async () => {
    const root = await mkdtemp(join(tmpdir(), 'ds-html-preview-'))
    dirs.push(root)
    const filePath = join(root, 'dashboard.html')
    await writeFile(filePath, '<html><body>ok</body></html>', 'utf8')

    const result = await getWorkspacePreviewUrl({
      path: filePath,
      workspaceRoot: root
    })
    expect(result.ok).toBe(true)
    if (!result.ok) return

    expect(result.url).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/dashboard\.html$/)
    const response = await fetch(result.url)
    expect(response.status).toBe(200)
    expect(await response.text()).toContain('ok')
  })

  it('serves an absolute html path even when workspaceRoot is unrelated', async () => {
    const root = await mkdtemp(join(tmpdir(), 'ds-html-preview-'))
    dirs.push(root)
    const filePath = join(root, 'report.html')
    await writeFile(filePath, '<html><body>report</body></html>', 'utf8')

    const result = await getWorkspacePreviewUrl({
      path: filePath,
      workspaceRoot: join(tmpdir(), 'other-workspace-does-not-matter')
    })
    expect(result.ok).toBe(true)
    if (!result.ok) return
    const response = await fetch(result.url)
    expect(response.status).toBe(200)
    expect(await response.text()).toContain('report')
  })

  it('rejects path escape attempts', async () => {
    const root = await mkdtemp(join(tmpdir(), 'ds-html-preview-'))
    dirs.push(root)
    await writeFile(join(root, 'in.html'), '<html></html>', 'utf8')

    const result = await getWorkspacePreviewUrl({
      path: '../outside.html',
      workspaceRoot: root
    })
    expect(result.ok).toBe(false)
  })

  it('serves a png image inside the workspace over localhost', async () => {
    const root = await mkdtemp(join(tmpdir(), 'ds-image-preview-'))
    dirs.push(root)
    // 1x1 transparent PNG
    const png = Buffer.from(
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
      'base64'
    )
    const filePath = join(root, 'dot.png')
    await writeFile(filePath, png)

    const result = await getWorkspacePreviewUrl({
      path: filePath,
      workspaceRoot: root
    })
    expect(result.ok).toBe(true)
    if (!result.ok) return

    expect(result.url).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/dot\.png$/)
    const response = await fetch(result.url)
    expect(response.status).toBe(200)
    expect(response.headers.get('content-type')).toMatch(/image\/png/)
    const bytes = Buffer.from(await response.arrayBuffer())
    expect(bytes.equals(png)).toBe(true)
  })
})
