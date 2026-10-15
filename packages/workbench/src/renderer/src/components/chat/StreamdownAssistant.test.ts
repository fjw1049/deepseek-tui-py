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

describe('Chinese bare URL boundaries', () => {
  it.each([false, true])('keeps trailing prose outside links (streaming=%s)', (streaming) => {
    for (const punctuation of ['），', '，', '。', '！', '？', '；', '：', '、', '】', '》', '”']) {
      const url = 'https://www.google.com/'
      const text = `首页（${url}${punctuation}页面加载正常。`
      const container = render(text, streaming)
      expect(container.querySelector('a')?.textContent).toBe(url)
      expect(container.querySelector('a')?.getAttribute('href')).toBe(url)
      expect(container.textContent).toBe(text)
    }
  })

  it.each([false, true])('handles www links and encoded punctuation (streaming=%s)', (streaming) => {
    const container = render('访问 www.example.com/中文，正文。', streaming)
    expect(container.querySelector('a')?.textContent).toBe('www.example.com/中文')
    expect(decodeURI(container.querySelector('a')!.getAttribute('href')!)).toBe('http://www.example.com/中文')
    const url = 'https://example.com/%EF%BC%8C?q=中文'
    const encoded = render(`${url}，正文。`, streaming)
    expect(encoded.querySelector('a')?.textContent).toBe(url)
    expect(decodeURI(encoded.querySelector('a')!.getAttribute('href')!)).toBe(decodeURI(url))
  })

  it.each([false, true])('preserves authored URLs and Chinese paths (streaming=%s)', (streaming) => {
    for (const source of [
      'https://example.com/中文路径?q=中文',
      '[中文链接](https://example.com/中文，路径)',
      '<https://example.com/中文，路径>',
      '[https://example.com/中文，路径](https://example.com/中文，路径)'
    ]) {
      const a = render(source, streaming).querySelector('a')!
      expect(decodeURI(a.getAttribute('href')!)).toBe(
        source.startsWith('https:') ? source : 'https://example.com/中文，路径'
      )
    }
    const code = render('`https://example.com/，正文`', streaming)
    expect(code.querySelector('a')).toBeNull()
    expect(code.querySelector('code')?.textContent).toBe('https://example.com/，正文')
  })
})
