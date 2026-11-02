import { describe, expect, it } from 'vitest'

import {
  bubbleReasonForTurn,
  canPetSpeak,
  mentionsPetName,
  PET_BUBBLE_COOLDOWN_MS,
  pickPetLineKey,
  rememberPetLine
} from './pet-bubble'
import type { PetTurnDigest } from './pet-turn-digest'

const turn = (patch: Partial<PetTurnDigest> = {}): PetTurnDigest => ({
  outcome: 'completed', durationMs: 5000, toolErrors: 0, testsFailed: false, diffLines: 0, ...patch
})

describe('bubbleReasonForTurn', () => {
  it('stays quiet for short, clean or cancelled turns', () => {
    expect(bubbleReasonForTurn(turn())).toBeNull()
    expect(bubbleReasonForTurn(turn({ outcome: 'cancelled', toolErrors: 3 }))).toBeNull()
  })

  it('picks the most useful news first', () => {
    expect(bubbleReasonForTurn(turn({ outcome: 'failed', testsFailed: true }))).toBe('turn_failed')
    expect(bubbleReasonForTurn(turn({ testsFailed: true, diffLines: 500 }))).toBe('tests_failed')
    expect(bubbleReasonForTurn(turn({ diffLines: 81, toolErrors: 2 }))).toBe('large_diff')
    expect(bubbleReasonForTurn(turn({ toolErrors: 2 }))).toBe('turn_recovered')
    expect(bubbleReasonForTurn(turn({ durationMs: 30_000 }))).toBe('turn_done')
  })
})

describe('canPetSpeak', () => {
  it('rate-limits chatter but not failures or direct contact', () => {
    expect(canPetSpeak('turn_done', 0, PET_BUBBLE_COOLDOWN_MS - 1)).toBe(false)
    expect(canPetSpeak('turn_done', 0, PET_BUBBLE_COOLDOWN_MS)).toBe(true)
    expect(canPetSpeak('tests_failed', 0, 1)).toBe(true)
    expect(canPetSpeak('petted', 0, 1)).toBe(true)
  })
})

describe('pickPetLineKey', () => {
  it('avoids the recent lines while others remain', () => {
    const recent = rememberPetLine(rememberPetLine([], 'petLinePetted1'), 'petLinePetted2')
    for (const roll of [0, 0.5, 0.99]) {
      expect(['petLinePetted3', 'petLinePetted4']).toContain(pickPetLineKey('petted', recent, () => roll))
    }
    expect(pickPetLineKey('stream_error', ['petLineStreamError1'], () => 0)).toBe('petLineStreamError1')
  })

  it('remembers only the last three lines', () => {
    expect(rememberPetLine(['a', 'b', 'c'], 'd')).toEqual(['b', 'c', 'd'])
  })
})

describe('mentionsPetName', () => {
  it('matches a Latin name as a word, also right next to Chinese text', () => {
    expect(mentionsPetName('boba你觉得呢', 'Boba')).toBe(true)
    expect(mentionsPetName('hey Boba, look', 'boba')).toBe(true)
    expect(mentionsPetName('bobatea is fine', 'Boba')).toBe(false)
  })

  it('matches a non-Latin name anywhere', () => {
    expect(mentionsPetName('小团子你好', '小团子')).toBe(true)
    expect(mentionsPetName('', 'Boba')).toBe(false)
  })
})
