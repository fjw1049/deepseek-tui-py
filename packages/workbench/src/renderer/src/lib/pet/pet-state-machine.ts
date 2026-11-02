import type { ChatBlock, ToolItemKind } from '../../agent/types'
import { petCycleMs, type PetStateId } from './pet-states'

/** A new kind of work has to hold this long before the body changes to match it. */
export const PET_WORK_SETTLE_MS = 1800

const READ_LIKE_TOOL = /\b(read|grep|glob|list_dir|search|find|cat)\b/i

export type PetWorkMode = Extract<PetStateId, 'running' | 'review'>
export type PetOneShotTier = 'decorative' | 'critical'

export type PetOneShot = {
  stateId: PetStateId
  tier: PetOneShotTier
  endsAt: number
}

export type PetMind = {
  work: PetWorkMode
  candidate: PetWorkMode
  candidateSince: number
  oneShot: PetOneShot | null
  /** Bumped per one-shot so replaying the same move still starts at frame 0. */
  playKey: number
}

export function initialPetMind(): PetMind {
  return { work: 'running', candidate: 'running', candidateSince: 0, oneShot: null, playKey: 0 }
}

export function classifyToolWork(tool: { summary: string; toolKind?: ToolItemKind }): PetWorkMode {
  if (tool.toolKind === 'file_change' || tool.toolKind === 'command_execution') return 'running'
  return READ_LIKE_TOOL.test(tool.summary) ? 'review' : 'running'
}

export function resetPetWork(mind: PetMind, now: number): PetMind {
  return { ...mind, work: 'running', candidate: 'running', candidateSince: now }
}

export function notePetWork(mind: PetMind, mode: PetWorkMode, now: number): PetMind {
  return mode === mind.candidate ? mind : { ...mind, candidate: mode, candidateSince: now }
}

/** Decorative moves play out or not at all; only a critical one may cut in. */
export function playPetOneShot(
  mind: PetMind,
  stateId: PetStateId,
  tier: PetOneShotTier,
  now: number,
  durationMs = petCycleMs(stateId)
): PetMind {
  if (tier === 'decorative' && mind.oneShot && now < mind.oneShot.endsAt) return mind
  return { ...mind, oneShot: { stateId, tier, endsAt: now + durationMs }, playKey: mind.playKey + 1 }
}

export function settlePetMind(mind: PetMind, now: number): PetMind {
  const oneShot = mind.oneShot && now >= mind.oneShot.endsAt ? null : mind.oneShot
  const work = mind.candidate !== mind.work && now - mind.candidateSince >= PET_WORK_SETTLE_MS
    ? mind.candidate
    : mind.work
  return oneShot === mind.oneShot && work === mind.work ? mind : { ...mind, oneShot, work }
}

export function nextPetWakeAt(mind: PetMind): number | null {
  const times = [
    mind.oneShot?.endsAt,
    mind.candidate !== mind.work ? mind.candidateSince + PET_WORK_SETTLE_MS : undefined
  ].filter((time): time is number => time != null)
  return times.length ? Math.min(...times) : null
}

export function resolvePetState(input: {
  mind: PetMind
  busy: boolean
  waiting: boolean
}): PetStateId {
  const { oneShot, work } = input.mind
  if (oneShot?.tier === 'critical') return oneShot.stateId
  if (input.waiting) return 'waiting'
  if (oneShot) return oneShot.stateId
  return input.busy ? work : 'idle'
}

export type PetPendingDecision = Extract<ChatBlock, { kind: 'approval' | 'elevation' | 'user_input' }>

export function findPetPendingDecision(blocks: ChatBlock[]): PetPendingDecision | null {
  for (const block of blocks) {
    if ((block.kind === 'approval' || block.kind === 'elevation' || block.kind === 'user_input') &&
      block.status === 'pending') {
      return block
    }
  }
  return null
}
