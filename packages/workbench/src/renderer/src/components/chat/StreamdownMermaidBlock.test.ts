import { describe, expect, it } from 'vitest'
import { truncateMermaidLabels } from './StreamdownMermaidBlock'

describe('truncateMermaidLabels', () => {
  it('leaves short labels alone', () => {
    const src = 'flowchart TD\n  A[short] --> B{ok}'
    expect(truncateMermaidLabels(src, 24)).toBe(src)
  })

  it('truncates long bracket labels', () => {
    const long = 'a'.repeat(40)
    const src = `flowchart TD\n  A[${long}] --> B`
    const out = truncateMermaidLabels(src, 24)
    expect(out).toContain('[aaaaaaaaaaaaaaaaaaaaaaa…]')
    expect(out).not.toContain(long)
  })
})
