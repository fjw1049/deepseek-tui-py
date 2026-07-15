import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { isHtmlPreviewPath } from '../../shared/html-preview'
import { isImagePreviewPath } from '../../shared/image-preview'
import {
  getWorkspacePreviewUrl,
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
