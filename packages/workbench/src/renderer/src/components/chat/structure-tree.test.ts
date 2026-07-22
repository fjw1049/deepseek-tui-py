import { describe, expect, it } from 'vitest'
import { looksLikeStructureTree } from './structure-tree'

describe('looksLikeStructureTree', () => {
  it('detects box-drawing package trees', () => {
    const src = `packages/
├── tui            terminal UI
├── ai             LLM API
└── agent          runtime`
    expect(looksLikeStructureTree(src, '')).toBe(true)
    expect(looksLikeStructureTree(src, 'text')).toBe(true)
  })

  it('rejects real language fences', () => {
    const src = `packages/
├── tui
└── ai`
    expect(looksLikeStructureTree(src, 'python')).toBe(false)
  })

  it('rejects ordinary plaintext logs', () => {
    const src = `error: failed to open
retrying in 2s
done`
    expect(looksLikeStructureTree(src, 'text')).toBe(false)
  })

  it('rejects short snippets', () => {
    expect(looksLikeStructureTree('packages/', '')).toBe(false)
  })
})
