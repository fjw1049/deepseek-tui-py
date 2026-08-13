import { describe, expect, it } from 'vitest'
import { isStreamdownFencedCode } from './StreamdownCode'

describe('isStreamdownFencedCode', () => {
  it('treats a lone paragraph code span as inline even when source lines differ', () => {
    // Streamdown's incomplete-markdown parser can assign a multi-line position
    // to `管理 **关键文件**：` while still parenting it under <p>. Emitting a
    // <div> code card from that node is what caused the hydration warning.
    expect(isStreamdownFencedCode({})).toBe(false)
    expect(isStreamdownFencedCode({ className: 'language-ts' })).toBe(false)
  })

  it('treats Streamdown-unwrapped fences as blocks', () => {
    expect(isStreamdownFencedCode({ 'data-block': 'true' })).toBe(true)
    expect(isStreamdownFencedCode({ 'data-block': true })).toBe(true)
  })
})
