// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ImageDocumentPreview } from './ImageDocumentPreview'
import { HtmlDocumentPreview } from './HtmlDocumentPreview'
import { useWorkspaceEditorStore } from '../../store/workspace-editor-store'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../../i18n', () => ({ default: { t: (key: string) => key } }))
let host: HTMLDivElement
let root: Root
const preview = vi.fn()
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  preview.mockReset()
  vi.stubGlobal('dsGui', { getWorkspaceHtmlPreviewUrl: preview })
  useWorkspaceEditorStore.setState({ previewVersion: 0 })
})
afterEach(() => { act(() => root.unmount()); host.remove(); vi.unstubAllGlobals() })

for (const [extension, Component, selector] of [
  ['png', ImageDocumentPreview, 'img'],
  ['html', HtmlDocumentPreview, 'iframe'],
  ['pdf', HtmlDocumentPreview, 'iframe']
] as const) {
  it(`refreshes ${extension} URLs and ignores a late response from the previous revision`, async () => {
    let resolveOld!: (value: { ok: true; url: string }) => void
    preview.mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve }))
      .mockResolvedValue({ ok: true, url: 'about:blank?file=current#page=2' })
    await act(async () => root.render(createElement(Component, { path: `a.${extension}`, workspaceRoot: '/repo' })))
    await act(async () => useWorkspaceEditorStore.setState({ previewVersion: 1 }))
    const current = host.querySelector(selector)!
    const url = new URL(current.getAttribute('src')!)
    expect(url.searchParams.get('_ds_revision')).toBe('1')
    expect(url.searchParams.get('file')).toBe('current')
    expect(url.hash).toBe('#page=2')
    await act(async () => resolveOld({ ok: true, url: 'about:blank?file=stale' }))
    expect(host.querySelector(selector)).toBe(current)
    expect(host.querySelector(selector)!.getAttribute('src')).toBe(url.href)
    expect(preview).toHaveBeenCalledTimes(2)
    await act(async () => useWorkspaceEditorStore.setState({ previewVersion: 2 }))
    expect(new URL(host.querySelector(selector)!.getAttribute('src')!).searchParams.get('_ds_revision')).toBe('2')
  })

  it(`recovers ${extension} preview errors and ignores a previous file failure`, async () => {
    let rejectOld!: (error: Error) => void
    preview.mockRejectedValueOnce(new Error('Preview unavailable'))
      .mockReturnValueOnce(new Promise((_, reject) => { rejectOld = reject }))
      .mockResolvedValue({ ok: true, url: 'about:blank?file=current' })
    await act(async () => root.render(createElement(Component, { path: `a.${extension}`, workspaceRoot: '/repo' })))
    expect(host.textContent).toContain('Preview unavailable')
    await act(async () => useWorkspaceEditorStore.setState({ previewVersion: 1 }))
    await act(async () => root.render(createElement(Component, { path: `b.${extension}`, workspaceRoot: '/repo' })))
    await act(async () => rejectOld(new Error('Old file failed')))
    expect(host.textContent).not.toContain('Old file failed')
    expect(host.querySelector(selector)).not.toBeNull()
    expect(preview).toHaveBeenLastCalledWith({ path: `b.${extension}`, workspaceRoot: '/repo' })
  })
}
