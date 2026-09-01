import { describe, expect, it } from 'vitest'

import {
  publishAttentionState,
  publishRecoveryDecisionKey
} from './publish-conflict-state'

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

  it('keeps real file paths attached to uncheckpointed recovery', () => {
    expect(
      publishAttentionState(['<unpublished-worktree-labor>', 'src/app.ts'], true)
    ).toEqual({
      kind: 'recovery',
      conflicts: ['src/app.ts']
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

  it('surfaces a missing worktree without treating its marker as a file path', () => {
    expect(publishAttentionState(['<missing-worktree>', 'src/app.ts'], true)).toEqual({
      kind: 'missing',
      conflicts: ['src/app.ts']
    })
  })

  it('gives a missing worktree priority over every recoverable state', () => {
    expect(
      publishAttentionState(
        ['<unpublished-worktree-labor>', 'src/app.ts', '<missing-worktree>'],
        true
      )
    ).toEqual({
      kind: 'missing',
      conflicts: ['<unpublished-worktree-labor>', 'src/app.ts']
    })
    expect(
      publishAttentionState(['<publish-failed>', '<missing-worktree>'], true)
    ).toEqual({ kind: 'missing', conflicts: ['<publish-failed>'] })
  })

  it('uses the structured issue and preserves marker-shaped filenames', () => {
    expect(
      publishAttentionState(['<publish-failed>', 'src/app.ts'], true, 'recovery')
    ).toEqual({
      kind: 'recovery',
      conflicts: ['<publish-failed>', 'src/app.ts']
    })
  })

  it('lets an explicit null issue treat marker-shaped entries as file conflicts', () => {
    expect(
      publishAttentionState(['<unpublished-worktree-labor>'], true, null)
    ).toEqual({
      kind: 'conflict',
      conflicts: ['<unpublished-worktree-labor>']
    })
  })

  it('removes only one legacy reason marker', () => {
    expect(
      publishAttentionState(['<publish-failed>', '<publish-failed>'], true)
    ).toEqual({
      kind: 'failure',
      conflicts: ['<publish-failed>']
    })
  })
})

describe('publishRecoveryDecisionKey', () => {
  it('changes when the runtime refreshes the same recovery paths', () => {
    const attention = publishAttentionState(['src/app.ts'], true, 'recovery')

    expect(publishRecoveryDecisionKey(attention, '2026-08-30T01:00:00Z')).not.toBe(
      publishRecoveryDecisionKey(attention, '2026-08-30T01:00:01Z')
    )
  })

  it('changes with the exact path set and disappears outside recovery', () => {
    const first = publishAttentionState(['src/a.ts'], true, 'recovery')
    const second = publishAttentionState(['src/b.ts'], true, 'recovery')
    const hidden = publishAttentionState([], false, null)

    expect(publishRecoveryDecisionKey(first, 'same')).not.toBe(
      publishRecoveryDecisionKey(second, 'same')
    )
    expect(publishRecoveryDecisionKey(hidden, 'same')).toBeNull()
  })
})
