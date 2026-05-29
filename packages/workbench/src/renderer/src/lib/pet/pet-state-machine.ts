import type { ChatBlock, ToolBlock } from '../../agent/types'
import type { PetStateId } from './pet-states'

export const MIN_PET_STATE_DWELL_MS = 300

const READ_LIKE_TOOL = /\b(read|grep|glob|list_dir|search|find|cat)\b/i

export type PetBurst = {
  stateId: PetStateId
  expiresAt: number
}

export type PetStateMachineInput = {
  busy: boolean
  blocks: ChatBlock[]
  liveReasoning: string
  turnErrorActive: boolean
  burst: PetBurst | null
  now: number
  lastState: PetStateId
  lastChangeAt: number
}

function hasPendingInteractive(blocks: ChatBlock[]): boolean {
  return blocks.some(
    (block) =>
      (block.kind === 'approval' && block.status === 'pending') ||
      (block.kind === 'elevation' && block.status === 'pending') ||
      (block.kind === 'user_input' && block.status === 'pending')
  )
}

function getCurrentTurnBlocks(blocks: ChatBlock[]): ChatBlock[] {
  let lastUserIdx = -1
  for (let i = blocks.length - 1; i >= 0; i -= 1) {
    if (blocks[i]?.kind === 'user') {
      lastUserIdx = i
      break
    }
  }
  if (lastUserIdx < 0) return []
  return blocks.slice(lastUserIdx + 1)
}

function hasToolErrorInCurrentTurn(blocks: ChatBlock[]): boolean {
  return getCurrentTurnBlocks(blocks).some(
    (block) => block.kind === 'tool' && block.status === 'error'
  )
}

function latestRunningTool(blocks: ChatBlock[]): ToolBlock | null {
  for (let i = blocks.length - 1; i >= 0; i -= 1) {
    const block = blocks[i]
    if (block?.kind === 'tool' && block.status === 'running') {
      return block
    }
  }
  return null
}

function isReadLikeTool(tool: ToolBlock): boolean {
  return READ_LIKE_TOOL.test(tool.summary)
}

function deriveCritical(input: PetStateMachineInput): PetStateId | null {
  if (input.turnErrorActive || hasToolErrorInCurrentTurn(input.blocks)) {
    return 'failed'
  }
  if (hasPendingInteractive(input.blocks)) {
    return 'waiting'
  }
  return null
}

function deriveSustained(input: PetStateMachineInput): PetStateId {
  if (!input.busy) return 'idle'

  const runningTool = latestRunningTool(input.blocks)
  if (runningTool && isReadLikeTool(runningTool)) {
    return 'review'
  }
  if (input.liveReasoning.trim() && !runningTool) {
    return 'review'
  }
  return 'running'
}

function deriveDecorativeBurst(
  burst: PetBurst | null,
  sustained: PetStateId,
  now: number
): PetStateId | null {
  if (!burst || now >= burst.expiresAt) return null
  if (sustained !== 'idle' && sustained !== 'running') return null
  return burst.stateId
}

export function resolvePetState(input: PetStateMachineInput): {
  stateId: PetStateId
  changedAt: number
} {
  const critical = deriveCritical(input)
  if (critical) {
    return critical === input.lastState
      ? { stateId: input.lastState, changedAt: input.lastChangeAt }
      : { stateId: critical, changedAt: input.now }
  }

  const sustained = deriveSustained(input)
  const decorative = deriveDecorativeBurst(input.burst, sustained, input.now)
  const next = decorative ?? sustained
  return applyDwell(next, input)
}

function applyDwell(
  next: PetStateId,
  input: PetStateMachineInput
): { stateId: PetStateId; changedAt: number } {
  if (next === input.lastState) {
    return { stateId: input.lastState, changedAt: input.lastChangeAt }
  }
  const elapsed = input.now - input.lastChangeAt
  if (input.lastState !== next && elapsed < MIN_PET_STATE_DWELL_MS) {
    return { stateId: input.lastState, changedAt: input.lastChangeAt }
  }
  return { stateId: next, changedAt: input.now }
}
