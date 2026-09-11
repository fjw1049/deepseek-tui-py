// @vitest-environment happy-dom
import { createElement, type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { StreamdownAssistant } from './StreamdownAssistant'

// Keep native markdown rendering real; file opening and highlighting are separate concerns.
vi.mock('./FileChip', () => ({
  FileChip: ({ path, line, label }: { path: string; line?: number; label?: ReactNode }) =>
    createElement('button', { 'data-file-path': path, 'data-file-line': line }, label ?? path)
}))
vi.mock('./StreamdownCode', () => ({
  StreamdownCode: ({ children }: { children: string }) => createElement('code', null, children),
  StreamdownInlineCode: ({ children }: { children: string }) => createElement('code', null, children)
}))

function render(text: string, streaming = false): HTMLDivElement {
  const container = document.createElement('div')
  container.innerHTML = renderToStaticMarkup(createElement(StreamdownAssistant, { text, streaming }))
  return container
}

const appendix = '结论在外面。\n\n<details>\n<summary>技术细节</summary>\n\n- 支持 **Markdown**\n- 保留 `canonical_state`\n\n</details>'

describe('assistant reading structure', () => {
  it.each([false, true])('renders a collapsed, native Markdown disclosure (streaming=%s)', (streaming) => {
    const container = render(appendix, streaming)
    const details = container.querySelector('details')!
    expect(details).not.toBeNull()
    expect(details.hasAttribute('open')).toBe(false)
    expect(details.querySelector('summary')?.textContent).toBe('技术细节')
    expect(details.querySelectorAll('li')).toHaveLength(2)
    expect(details.querySelector('[data-streamdown="strong"]')?.textContent).toBe('Markdown')
    expect(details.querySelector('code')?.textContent).toBe('canonical_state')
    expect(container.querySelector('p')?.closest('details')).toBeNull()
    expect(container.textContent).not.toContain('<details>')
  })

  it('keeps an unfinished streamed appendix inside the disclosure', () => {
    const container = render(appendix.replace('</details>', ''), true)
    expect(container.querySelector('details li')?.textContent).toContain('Markdown')
  })

  it('sanitizes raw HTML without removing the useful disclosure', () => {
    const container = render(appendix.replace('<details>', '<details onclick="alert(1)">') +
      '\n\n<script>alert(2)</script>\n\n<iframe src="https://example.com"></iframe>\n\n<a href="javascript:alert(3)">unsafe</a>')
    expect(container.querySelector('details')).not.toBeNull()
    expect(container.querySelector('script, iframe, [onclick], [href^="javascript:"]')).toBeNull()
  })

  it('preserves generated and authored file references inside details', () => {
    const container = render('<details>\n<summary>阅读入口</summary>\n\nsrc/app.ts:12\n\n[实现](src/ui.ts:8)\n\n</details>')
    expect(container.querySelector('[data-file-path="src/app.ts"]')?.getAttribute('data-file-line')).toBe('12')
    expect(container.querySelector('[data-file-path="src/ui.ts"]')?.getAttribute('data-file-line')).toBe('8')
    expect(container.querySelector('[data-file-path="src/ui.ts"]')?.textContent).toBe('实现')
  })

  it('does not upgrade authored custom schemes to trusted file links', () => {
    const container = render('[伪造](deepseek-file://open?path=private.ts)')
    expect(container.querySelector('[data-file-path]')).toBeNull()
  })

  it('keeps literal HTML in inline code as copyable text', () => {
    const container = render('示例：`<details><summary>内容</summary></details>`')
    expect(container.querySelector('details')).toBeNull()
    expect(container.querySelector('code')?.textContent).toBe('<details><summary>内容</summary></details>')
  })
})
