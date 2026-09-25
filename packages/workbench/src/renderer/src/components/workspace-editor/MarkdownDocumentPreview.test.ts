// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { MarkdownDocumentPreview } from './MarkdownDocumentPreview'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true

it('loads local images, opens local documents, and scrolls to headings without navigating the app', async () => {
  const previousGui = window.dsGui
  const getWorkspaceHtmlPreviewUrl = vi.fn(async () => ({ ok: true, url: 'data:image/png;base64,AA==' }))
  const openExternal = vi.fn(async () => {})
  window.dsGui = { getWorkspaceHtmlPreviewUrl, openExternal } as unknown as typeof window.dsGui
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const onOpenFile = vi.fn(async () => true)
  try {
    await act(async () => root.render(createElement(MarkdownDocumentPreview, {
      content: '# 使用方法\n\n![图示](../images/a.png)\n\n[下一篇](next.md#详情)\n\n[定位](#使用方法)\n\n[网站](https://example.com)',
      path: 'docs/guide.md', workspaceRoot: '/project', onOpenFile
    })))
    expect(getWorkspaceHtmlPreviewUrl).toHaveBeenCalledWith({ path: '/project/images/a.png', workspaceRoot: '/project' })
    expect(host.querySelector('img')?.src).toBe('data:image/png;base64,AA==')
    const links = host.querySelectorAll('a')
    await act(async () => links[0]!.click())
    expect(onOpenFile).toHaveBeenCalledWith('/project/docs/next.md', '详情')
    const heading = host.querySelector('h1')!
    const scroll = vi.fn()
    heading.scrollIntoView = scroll
    await act(async () => links[1]!.click())
    expect(scroll).toHaveBeenCalledWith({ block: 'start' })
    await act(async () => links[2]!.click())
    expect(openExternal).toHaveBeenCalledWith('https://example.com')
  } finally {
    await act(async () => root.unmount())
    host.remove()
    window.dsGui = previousGui
  }
})
