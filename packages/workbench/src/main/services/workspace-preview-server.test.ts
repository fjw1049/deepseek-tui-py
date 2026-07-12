import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { isHtmlPreviewPath } from '../../shared/html-preview'
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
})
