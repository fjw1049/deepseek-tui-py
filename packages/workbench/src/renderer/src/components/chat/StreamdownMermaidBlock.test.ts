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

  it('keeps quote wrappers when truncating ["…"] labels', () => {
    const src =
      'graph TB\n  P["🏠 Parent Session (depth=0)"]:::dispatch\n  P -->|"task"| CHECK\n  subgraph s["Validation"]\n    CHECK{"前置校验"}\n  end'
    const out = truncateMermaidLabels(src, 24)
    expect(out).not.toContain('(depth=0)')
    // Closing quote must survive — otherwise Mermaid treats later lines as
    // still inside the string and fails with "got STR" near subgraph.
    expect(out).toMatch(/P\["[^"\n]+"\]/)
    expect(out).toContain('subgraph s["Validation"]')
  })
})
