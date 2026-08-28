import { describe, expect, it } from 'vitest'

import { publishAttentionState } from './publish-conflict-state'

describe('publishAttentionState', () => {
  it('keeps ordinary pending and waiting sync state invisible', () => {
    expect(publishAttentionState([], false)).toEqual({ kind: 'hidden', conflicts: [] })
  })

  it('surfaces uncheckpointed recovery as a user decision', () => {
    expect(publishAttentionState(['<unpublished-worktree-labor>'], true)).toEqual({
      kind: 'recovery',
      conflicts: []
    })
  })

  it('surfaces automatic sync failures with technical markers removed', () => {
    expect(publishAttentionState(['<publish-failed>'], true)).toEqual({
      kind: 'failure',
      conflicts: []
    })
  })

  it('shows only real conflicting file paths', () => {
    expect(publishAttentionState(['src/app.ts', 'README.md'], true)).toEqual({
      kind: 'conflict',
      conflicts: ['src/app.ts', 'README.md']
    })
  })
})
