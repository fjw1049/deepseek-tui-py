import { describe, expect, it } from 'vitest'

import type { ChatBlock } from '../../agent/types'
import { resolvePetState } from './pet-state-machine'

function baseInput(
  overrides: Partial<Parameters<typeof resolvePetState>[0]> = {}
): Parameters<typeof resolvePetState>[0] {
  return {
    busy: false,
    blocks: [],
    liveReasoning: '',
    turnErrorActive: false,
    burst: null,
    now: 10_000,
    lastState: 'idle',
    lastChangeAt: 0,
    ...overrides
  }
}

describe('resolvePetState', () => {
  it('returns idle when not busy', () => {
    expect(resolvePetState(baseInput()).stateId).toBe('idle')
  })

  it('prefers waiting over decorative burst', () => {
    const blocks: ChatBlock[] = [
      {
        kind: 'approval',
        id: 'a1',
        approvalId: 'ap1',
        summary: 'Write file',
        status: 'pending'
      }
    ]
    const result = resolvePetState(
      baseInput({
        busy: true,
        blocks,
        burst: { stateId: 'jumping', expiresAt: 20_000 }
      })
    )
    expect(result.stateId).toBe('waiting')
  })

  it('uses jumping burst only when sustained is idle', () => {
    const result = resolvePetState(
      baseInput({
        burst: { stateId: 'jumping', expiresAt: 20_000 },
        now: 10_000
      })
    )
    expect(result.stateId).toBe('jumping')
  })

  it('does not fail from historical tool errors outside current turn', () => {
    const blocks: ChatBlock[] = [
      { kind: 'user', id: 'u-old', text: 'old' },
      { kind: 'tool', id: 't-old', summary: 'Run', status: 'error' },
      { kind: 'user', id: 'u-new', text: 'new' },
      { kind: 'assistant', id: 'a1', text: 'ok' }
    ]
    expect(
      resolvePetState(
        baseInput({
          busy: false,
          blocks
        })
      ).stateId
    ).toBe('idle')
  })

  it('fails on tool error in current turn', () => {
    const blocks: ChatBlock[] = [
      { kind: 'user', id: 'u1', text: 'go' },
      { kind: 'tool', id: 't1', summary: 'Run', status: 'error' }
    ]
    expect(
      resolvePetState(
        baseInput({
          busy: true,
          blocks
        })
      ).stateId
    ).toBe('failed')
  })

  it('respects min dwell time', () => {
    const first = resolvePetState(
      baseInput({
        busy: true,
        lastState: 'idle',
        lastChangeAt: 9_800,
        now: 10_000
      })
    )
    expect(first.stateId).toBe('idle')

    const second = resolvePetState(
      baseInput({
        busy: true,
        lastState: first.stateId,
        lastChangeAt: first.changedAt,
        now: 10_050
      })
    )
    expect(second.stateId).toBe('idle')

    const third = resolvePetState(
      baseInput({
        busy: true,
        lastState: second.stateId,
        lastChangeAt: second.changedAt,
        now: 10_200
      })
    )
    expect(third.stateId).toBe('running')
  })

  it('does not delay critical waiting behind min dwell', () => {
    const blocks: ChatBlock[] = [
      {
        kind: 'approval',
        id: 'a1',
        approvalId: 'ap1',
        summary: 'Write file',
        status: 'pending'
      }
    ]
    expect(
      resolvePetState(
        baseInput({
          busy: true,
          blocks,
          lastState: 'jumping',
          lastChangeAt: 9_950,
          now: 10_000
        })
      ).stateId
    ).toBe('waiting')
  })
})
