import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { SharedCodeBlock, highlightCodeHtml } from './SharedCodeBlock'
import { StructureBlock } from './StructureBlock'

vi.mock('react-i18next', async (importOriginal) => ({
  ...await importOriginal<typeof import('react-i18next')>(),
  useTranslation: () => ({ t: () => '结构' })
}))

describe('special text presentation', () => {
  it('uses the same card and typography for structure and plain text', () => {
    const content = 'root/\n  child\n\n  next'
    expect(renderToStaticMarkup(createElement(StructureBlock, { content }))).toBe(
      renderToStaticMarkup(createElement(SharedCodeBlock, { code: content, title: '结构' }))
    )
  })

  it('preserves indentation and empty lines without inserting extra whitespace', async () => {
    const html = await highlightCodeHtml('root/\n\n  <child>', 'text')
    expect(html).toContain('<span class="line">root/</span>\n<span class="line"></span>\n<span class="line">  &lt;child&gt;</span>')
  })
})
