import type { ChatBlock, TurnDiffUpdatedPayload } from '../../agent/types'

export type PetTurnOutcome = 'completed' | 'failed' | 'cancelled'

/** What the pet may react to once a turn is over, without keeping the blocks. */
export type PetTurnDigest = {
  outcome: PetTurnOutcome
  durationMs: number
  toolErrors: number
  testsFailed: boolean
  diffLines: number
}

const TESTS_FAILED =
  /\b[1-9]\d* (?:tests? )?(?:failed|failing)\b|\btests? failed\b|^FAIL\b|^FAILED\b/im
const TAIL_CHARS = 4000

export function petTurnOutcome(
  status?: 'completed' | 'failed' | 'cancelled',
  taskStatus?: string | null
): PetTurnOutcome {
  if (status === 'cancelled') return 'cancelled'
  if (status === 'failed' || taskStatus === 'partial' || taskStatus === 'blocked') return 'failed'
  return 'completed'
}

export function digestPetTurn(input: {
  outcome: PetTurnOutcome
  blocks: ChatBlock[]
  durationMs: number
  diff?: Pick<TurnDiffUpdatedPayload, 'totals'> | null
}): PetTurnDigest {
  let lastUser = -1
  for (let i = input.blocks.length - 1; i >= 0; i -= 1) {
    if (input.blocks[i]?.kind === 'user') {
      lastUser = i
      break
    }
  }
  const tools = input.blocks.slice(lastUser + 1).flatMap((block) => (block.kind === 'tool' ? [block] : []))
  const lastRun = tools.filter((tool) => tool.toolKind === 'command_execution').at(-1)
  const totals = input.diff?.totals
  return {
    outcome: input.outcome,
    durationMs: Math.max(0, input.durationMs),
    toolErrors: tools.filter((tool) => tool.status === 'error').length,
    // Only the last run counts: an earlier red test the agent fixed is not news.
    testsFailed: TESTS_FAILED.test(lastRun?.detail?.slice(-TAIL_CHARS) ?? ''),
    diffLines: (totals?.additions ?? 0) + (totals?.deletions ?? 0)
  }
}
