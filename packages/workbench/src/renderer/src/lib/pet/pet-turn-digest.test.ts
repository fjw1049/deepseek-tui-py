import { describe, expect, it } from 'vitest'

import type { ChatBlock } from '../../agent/types'
import { digestPetTurn, petTurnOutcome } from './pet-turn-digest'

describe('petTurnOutcome', () => {
  it('separates a cancel from a failure', () => {
    expect(petTurnOutcome('completed')).toBe('completed')
    expect(petTurnOutcome(undefined)).toBe('completed')
    expect(petTurnOutcome('cancelled', 'partial')).toBe('cancelled')
    expect(petTurnOutcome('failed')).toBe('failed')
    expect(petTurnOutcome('completed', 'blocked')).toBe('failed')
  })
})

describe('digestPetTurn', () => {
  const blocks: ChatBlock[] = [
    { kind: 'user', id: 'u0', text: 'old' },
    { kind: 'tool', id: 't0', summary: 'old', status: 'error' },
    { kind: 'user', id: 'u1', text: 'now' },
    { kind: 'tool', id: 't1', summary: 'grep', status: 'error' },
    { kind: 'tool', id: 't2', summary: 'npm test', status: 'success', toolKind: 'command_execution',
      detail: 'Tests: 2 failed, 40 passed' },
    { kind: 'tool', id: 't3', summary: 'npm test', status: 'success', toolKind: 'command_execution',
      detail: 'Tests: 42 passed' }
  ]

  it('counts only this turn and judges tests by the last run', () => {
    expect(digestPetTurn({
      outcome: 'completed', blocks, durationMs: 1200,
      diff: { totals: { files: 2, additions: 70, deletions: 20 } }
    })).toEqual({ outcome: 'completed', durationMs: 1200, toolErrors: 1, testsFailed: false, diffLines: 90 })
  })

  it('reports a failing last run', () => {
    expect(digestPetTurn({ outcome: 'completed', blocks: blocks.slice(0, 5), durationMs: -5 }))
      .toMatchObject({ testsFailed: true, durationMs: 0, diffLines: 0 })
  })
})
