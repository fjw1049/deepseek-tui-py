import { describe, expect, it } from 'vitest'

import type { ToolBlock } from '../../../agent/types'
import { buildToolRenderContext } from './render-context'

// added=2 (new lines 2,3), removed=1; first changed line in the new file = 2.
const DIFF = [
  '--- a/src/foo.ts',
  '+++ b/src/foo.ts',
  '@@ -1,3 +1,4 @@',
  ' line1',
  '-old',
  '+new1',
  '+new2',
  ' line3'
].join('\n')

function fileChangeBlock(overrides: Partial<ToolBlock> = {}): ToolBlock {
  return {
    kind: 'tool',
    id: 'tool_1',
    summary: 'edit_file: path="src/foo.ts"',
    status: 'success',
    toolKind: 'file_change',
    detail: DIFF,
    ...overrides
  }
}

describe('buildToolRenderContext diff stats', () => {
  it('prefers exact mutation counts from meta over parsed counts', () => {
    const ctx = buildToolRenderContext(
      fileChangeBlock({ meta: { mutation: { additions: 7, deletions: 3 } } })
    )
    expect(ctx.diffStats).toEqual({ added: 7, removed: 3 })
  })

  it('falls back to counting the patch when meta has no mutation', () => {
    expect(buildToolRenderContext(fileChangeBlock()).diffStats).toEqual({
      added: 2,
      removed: 1
    })
  })

  it('omits stats when the mutation reports zero changes and there is no patch', () => {
    const ctx = buildToolRenderContext(
      fileChangeBlock({
        detail: undefined,
        meta: { mutation: { additions: 0, deletions: 0 } }
      })
    )
    expect(ctx.diffStats).toBeUndefined()
  })

  it('omits stats when there is neither mutation meta nor a diff', () => {
    const ctx = buildToolRenderContext(fileChangeBlock({ detail: 'wrote file ok' }))
    expect(ctx.diffStats).toBeUndefined()
  })

  it('omits stats for non-file-change tools', () => {
    const ctx = buildToolRenderContext(fileChangeBlock({ toolKind: 'tool_call' }))
    expect(ctx.diffStats).toBeUndefined()
  })
})

describe('buildToolRenderContext edit line', () => {
  it('prefers meta.mutation.line_start when present', () => {
    const ctx = buildToolRenderContext(
      fileChangeBlock({ meta: { mutation: { line_start: 42 } } })
    )
    expect(ctx.editLine).toBe(42)
  })

  it('falls back to the first added line parsed from the patch', () => {
    expect(buildToolRenderContext(fileChangeBlock()).editLine).toBe(2)
  })

  it('parses the patch when line_start is not a valid line number', () => {
    const ctx = buildToolRenderContext(
      fileChangeBlock({ meta: { mutation: { line_start: 0 } } })
    )
    expect(ctx.editLine).toBe(2)
  })

  it('is undefined when there is no line hint and the detail is not a diff', () => {
    const ctx = buildToolRenderContext(fileChangeBlock({ detail: 'wrote file ok' }))
    expect(ctx.editLine).toBeUndefined()
  })

  it('is undefined for non-file-change tools', () => {
    const ctx = buildToolRenderContext(fileChangeBlock({ toolKind: 'tool_call' }))
    expect(ctx.editLine).toBeUndefined()
  })
})

describe('buildToolRenderContext label', () => {
  it('uses the edit label for shell-detected file changes', () => {
    const ctx = buildToolRenderContext(
      fileChangeBlock({ summary: 'exec_shell: update src/foo.ts' })
    )
    expect(ctx.label).toBe('编辑文件')
  })

  it('keeps genuine edit tool labels', () => {
    const ctx = buildToolRenderContext(
      fileChangeBlock({ summary: 'apply_patch: update src/foo.ts' })
    )
    expect(ctx.label).toBe('应用补丁')
  })

  it('keeps the command label for real shell executions', () => {
    const ctx = buildToolRenderContext(
      fileChangeBlock({
        summary: 'exec_shell: npm test',
        toolKind: 'command_execution'
      })
    )
    expect(ctx.label).toBe('执行命令')
  })
})
