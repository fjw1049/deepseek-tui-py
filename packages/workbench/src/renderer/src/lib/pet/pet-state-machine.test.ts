import { describe, expect, it } from 'vitest'

import type { ChatBlock } from '../../agent/types'
import {
  classifyToolWork,
  findPetPendingDecision,
  initialPetMind,
  nextPetWakeAt,
  notePetWork,
  PET_WORK_SETTLE_MS,
  playPetOneShot,
  resetPetWork,
  resolvePetState,
  settlePetMind
} from './pet-state-machine'

const idle = { busy: false, waiting: false }
const busy = { busy: true, waiting: false }

describe('resolvePetState', () => {
  it('is idle when nothing happens and works while busy', () => {
    expect(resolvePetState({ mind: initialPetMind(), ...idle })).toBe('idle')
    expect(resolvePetState({ mind: initialPetMind(), ...busy })).toBe('running')
  })

  it('lets waiting interrupt a decorative move but not a critical one', () => {
    const jumping = playPetOneShot(initialPetMind(), 'jumping', 'decorative', 0)
    expect(resolvePetState({ mind: jumping, busy: true, waiting: true })).toBe('waiting')
    const failed = playPetOneShot(initialPetMind(), 'failed', 'critical', 0)
    expect(resolvePetState({ mind: failed, busy: true, waiting: true })).toBe('failed')
  })

  it('plays a decorative move over work instead of being cut off by it', () => {
    let mind = playPetOneShot(initialPetMind(), 'jumping', 'decorative', 0)
    mind = notePetWork(mind, 'review', 100)
    mind = settlePetMind(mind, 300)
    expect(resolvePetState({ mind, ...busy })).toBe('jumping')
    mind = settlePetMind(mind, 840)
    expect(resolvePetState({ mind, ...busy })).toBe('running')
  })
})

describe('one-shot moves', () => {
  it('drops a decorative move that would interrupt another one', () => {
    const waving = playPetOneShot(initialPetMind(), 'waving', 'decorative', 0)
    expect(playPetOneShot(waving, 'jumping', 'decorative', 300)).toBe(waving)
    expect(playPetOneShot(waving, 'jumping', 'decorative', 700).oneShot?.stateId).toBe('jumping')
  })

  it('lets a critical move replace a decorative one and replays from a new key', () => {
    const waving = playPetOneShot(initialPetMind(), 'waving', 'decorative', 0)
    const failed = playPetOneShot(waving, 'failed', 'critical', 100)
    expect(failed.oneShot).toEqual({ stateId: 'failed', tier: 'critical', endsAt: 1320 })
    expect(failed.playKey).toBe(waving.playKey + 1)
  })

  it('ends exactly after one cycle of its row', () => {
    const mind = playPetOneShot(initialPetMind(), 'waving', 'decorative', 1000)
    expect(nextPetWakeAt(mind)).toBe(1700)
    expect(settlePetMind(mind, 1699).oneShot).not.toBeNull()
    expect(settlePetMind(mind, 1700).oneShot).toBeNull()
  })
})

describe('work mode', () => {
  it('only changes after the new kind of work has held for a while', () => {
    let mind = notePetWork(initialPetMind(), 'review', 1000)
    expect(nextPetWakeAt(mind)).toBe(1000 + PET_WORK_SETTLE_MS)
    expect(settlePetMind(mind, 1000 + PET_WORK_SETTLE_MS - 1).work).toBe('running')
    mind = settlePetMind(mind, 1000 + PET_WORK_SETTLE_MS)
    expect(resolvePetState({ mind, ...busy })).toBe('review')
  })

  it('does not flicker when tools alternate faster than the settle time', () => {
    let mind = initialPetMind()
    for (let at = 0; at < 10_000; at += 400) {
      mind = notePetWork(mind, (at / 400) % 2 ? 'review' : 'running', at)
      mind = settlePetMind(mind, at + 399)
      expect(mind.work).toBe('running')
    }
  })

  it('starts each turn from plain work', () => {
    const settled = settlePetMind(notePetWork(initialPetMind(), 'review', 0), PET_WORK_SETTLE_MS)
    expect(resetPetWork(settled, 5000)).toMatchObject({ work: 'running', candidate: 'running' })
  })

  it('classifies edits and commands as running and lookups as review', () => {
    expect(classifyToolWork({ summary: 'read src/a.ts' })).toBe('review')
    expect(classifyToolWork({ summary: 'grep foo', toolKind: 'command_execution' })).toBe('running')
    expect(classifyToolWork({ summary: 'patch', toolKind: 'file_change' })).toBe('running')
  })
})

describe('findPetPendingDecision', () => {
  it('finds a pending approval and ignores resolved ones', () => {
    const blocks: ChatBlock[] = [
      { kind: 'approval', id: 'a0', approvalId: 'x', summary: 'old', status: 'allowed' },
      { kind: 'approval', id: 'a1', approvalId: 'y', summary: 'Write file', status: 'pending' }
    ]
    expect(findPetPendingDecision(blocks)?.id).toBe('a1')
    expect(findPetPendingDecision(blocks.slice(0, 1))).toBeNull()
  })
})
