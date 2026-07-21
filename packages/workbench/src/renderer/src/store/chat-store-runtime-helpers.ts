import type {
  ChatBlock,
  UserInputQuestion,
  UserMessageEventPayload,
  WorkflowProgressPayload
} from '../agent/types'
import { finalizeOrphanSubagentBlocks } from '../lib/subagent-mailbox'
import { normalizeWorkspaceRoot } from '../lib/workspace-path'
import type { ChatState, QueuedUserMessage } from './chat-store-types'

export type PendingApprovalPayload = {
  approvalId: string
  summary: string
  inputSummary?: string
  impacts?: string[]
  riskLevel?: string
  presentationRisk?: string
  toolName?: string
}

export function threadBelongsToWorkspace(
  thread: { workspace?: string },
  workspaceRoot: string
): boolean {
  const normalizedWorkspace = normalizeWorkspaceRoot(workspaceRoot)
  if (!normalizedWorkspace) return false
  return normalizeWorkspaceRoot(thread.workspace) === normalizedWorkspace
}

export type PendingUserInputPayload = {
  requestId: string
  questions: UserInputQuestion[]
}

export function mergePendingUserInputBlocks(
  blocks: ChatBlock[],
  pending: PendingUserInputPayload[]
): { blocks: ChatBlock[]; firstAddedBlockId: string | null } {
  if (!pending.length) return { blocks, firstAddedBlockId: null }
  const existing = new Set(
    blocks
      .filter((block) => block.kind === 'user_input')
      .map((block) => block.requestId)
  )
  const additions: ChatBlock[] = []
  for (const item of pending) {
    if (!item.requestId || existing.has(item.requestId)) continue
    existing.add(item.requestId)
    additions.push({
      kind: 'user_input',
      id: item.requestId,
      createdAt: new Date().toISOString(),
      requestId: item.requestId,
      questions: item.questions,
      status: 'pending'
    })
  }
  if (!additions.length) return { blocks, firstAddedBlockId: null }
  return {
    blocks: [...blocks, ...additions],
    firstAddedBlockId: additions[0]?.id ?? null
  }
}

export function mergePendingApprovalBlocks(
  blocks: ChatBlock[],
  pending: PendingApprovalPayload[]
): { blocks: ChatBlock[]; firstAddedBlockId: string | null } {
  if (!pending.length) return { blocks, firstAddedBlockId: null }
  const existing = new Set(
    blocks
      .filter((block) => block.kind === 'approval')
      .map((block) => block.approvalId)
  )
  const additions: ChatBlock[] = []
  for (const item of pending) {
    if (!item.approvalId || existing.has(item.approvalId)) continue
    existing.add(item.approvalId)
    additions.push({
      kind: 'approval',
      id: `approval-${item.approvalId}`,
      createdAt: new Date().toISOString(),
      approvalId: item.approvalId,
      summary: item.summary,
      inputSummary: item.inputSummary,
      impacts: item.impacts,
      riskLevel: item.riskLevel,
      presentationRisk: item.presentationRisk,
      toolName: item.toolName,
      status: 'pending'
    })
  }
  if (!additions.length) return { blocks, firstAddedBlockId: null }
  return {
    blocks: [...blocks, ...additions],
    firstAddedBlockId: additions[0]?.id ?? null
  }
}

export type PendingEvolutionPayload = {
  recordId: string
  kind: string
  summary: string
  assetPath?: string
}

export function mergePendingEvolutionBlocks(
  blocks: ChatBlock[],
  pending: PendingEvolutionPayload[]
): { blocks: ChatBlock[]; firstAddedBlockId: string | null } {
  if (!pending.length) return { blocks, firstAddedBlockId: null }
  const existing = new Set(
    blocks
      .filter((block) => block.kind === 'evolution')
      .map((block) => block.recordId)
  )
  const additions: ChatBlock[] = []
  for (const item of pending) {
    if (!item.recordId || existing.has(item.recordId)) continue
    existing.add(item.recordId)
    additions.push({
      kind: 'evolution',
      id: `evolution-${item.recordId}`,
      createdAt: new Date().toISOString(),
      recordId: item.recordId,
      kindLabel: item.kind,
      summary: item.summary,
      assetPath: item.assetPath,
      status: 'pending'
    })
  }
  if (!additions.length) return { blocks, firstAddedBlockId: null }
  return {
    blocks: [...blocks, ...additions],
    firstAddedBlockId: additions[0]?.id ?? null
  }
}

export function countPendingApprovals(blocks: ChatBlock[]): number {
  return blocks.filter((block) => block.kind === 'approval' && block.status === 'pending').length
}

type ThreadDetailProviderLike = {
  getThreadDetail: (threadId: string) => Promise<{ blocks: ChatBlock[] }>
}

export function hasPendingRuntimeWork(block: ChatBlock): boolean {
  if (block.kind === 'tool') return block.status === 'running'
  if (block.kind === 'approval') return block.status === 'pending'
  if (block.kind === 'evolution') return block.status === 'pending'
  if (block.kind === 'user_input') return block.status === 'pending'
  if (block.kind === 'workflow') return block.status === 'running'
  if (block.kind === 'subagent') {
    return block.status === 'pending' || block.status === 'running'
  }
  return false
}

/**
 * After an interrupt (or force-clear), mark in-flight tools/workflows/subagents
 * terminal so `hasPendingRuntimeWork` cannot keep the composer stuck in queue mode.
 */
export function finalizeOrphanRuntimeBlocks(blocks: ChatBlock[]): ChatBlock[] {
  const withSubagents = finalizeOrphanSubagentBlocks(blocks)
  let changed = withSubagents !== blocks
  const next = withSubagents.map((block) => {
    if (block.kind === 'tool' && block.status === 'running') {
      changed = true
      return { ...block, status: 'error' as const }
    }
    if (block.kind === 'workflow' && block.status === 'running') {
      changed = true
      return { ...block, status: 'cancelled' as const }
    }
    return block
  })
  return changed ? next : blocks
}

/** Move a queued message to the front (for send-now). Returns null if missing. */
export function moveQueuedMessageToFront(
  queued: QueuedUserMessage[],
  id: string
): QueuedUserMessage[] | null {
  const idx = queued.findIndex((message) => message.id === id)
  if (idx < 0) return null
  if (idx === 0) return queued
  const target = queued[idx]
  return [target, ...queued.slice(0, idx), ...queued.slice(idx + 1)]
}

export function upsertWorkflowBlock(
  blocks: ChatBlock[],
  ev: WorkflowProgressPayload
): ChatBlock[] {
  const status: 'running' | 'completed' | 'failed' | 'cancelled' | 'timed_out' =
    ev.completed
      ? ev.status === 'timed_out'
        ? 'timed_out'
        : ev.status === 'cancelled'
          ? 'cancelled'
          : ev.status === 'failed'
            ? 'failed'
            : ev.snapshot.error_count > 0 && ev.snapshot.done_count === 0
              ? 'failed'
              : 'completed'
      : 'running'
  const runId = ev.runId?.trim() || undefined
  const nextBlock: ChatBlock = {
    kind: 'workflow',
    id: ev.toolCallId,
    toolCallId: ev.toolCallId,
    workflowName: ev.workflowName,
    status,
    snapshot: ev.snapshot,
    createdAt: new Date().toISOString(),
    ...(runId ? { runId } : {})
  }
  const idx = blocks.findIndex(
    (b) => b.kind === 'workflow' && b.toolCallId === ev.toolCallId
  )
  let next: ChatBlock[]
  if (idx < 0) {
    next = [...blocks, nextBlock]
  } else {
    const current = blocks[idx]
    const merged: ChatBlock =
      current.kind === 'workflow'
        ? {
            ...current,
            ...nextBlock,
            createdAt: current.createdAt ?? nextBlock.createdAt,
            runId: runId || current.runId
          }
        : nextBlock
    next = [...blocks]
    next[idx] = merged
  }
  // Same run_id resumed under a new tool_call_id: drop older terminal cards so
  // ProcessTray does not show cancelled + running side by side.
  if (runId && status === 'running') {
    next = next.filter(
      (b) =>
        !(
          b.kind === 'workflow' &&
          b.runId === runId &&
          b.toolCallId !== ev.toolCallId &&
          b.status !== 'running'
        )
    )
  }
  return next
}

export function threadSnapshotLooksRunning(blocks: ChatBlock[], threadStatus?: string): boolean {
  if (runtimeStatusLooksRunning(threadStatus)) return true
  return blocks.some(hasPendingRuntimeWork)
}

/** True when the thread/runtime status itself claims an active turn. */
export function threadStatusLooksActive(threadStatus?: string): boolean {
  return runtimeStatusLooksRunning(threadStatus)
}

export function findLatestUserBlockId(blocks: ChatBlock[]): string | null {
  for (let idx = blocks.length - 1; idx >= 0; idx -= 1) {
    const block = blocks[idx]
    if (block?.kind === 'user') return block.id
  }
  return null
}

export function upsertUserBlock(blocks: ChatBlock[], ev: UserMessageEventPayload): ChatBlock[] {
  const nextBlock: ChatBlock = {
    kind: 'user',
    id: ev.itemId,
    createdAt: ev.createdAt,
    text: ev.text,
    ...(ev.modelLabel ? { modelLabel: ev.modelLabel } : {})
  }
  const existingIndex = blocks.findIndex((block) => block.kind === 'user' && block.id === ev.itemId)
  if (existingIndex < 0) return [...blocks, nextBlock]
  const current = blocks[existingIndex]
  const merged: ChatBlock = {
    ...current,
    ...nextBlock,
    createdAt: current.createdAt ?? nextBlock.createdAt
  }
  const next = [...blocks]
  next[existingIndex] = merged
  return next
}

export function reconcileOptimisticUserBlock(
  blocks: ChatBlock[],
  optimisticId: string,
  runtimeId: string,
  fallbackText?: string,
  modelLabel?: string
): ChatBlock[] {
  return blocks.map((block) => {
    if (block.kind !== 'user' || block.id !== optimisticId) return block
    return {
      ...block,
      id: runtimeId,
      ...(fallbackText && !block.text.trim() ? { text: fallbackText } : {}),
      ...(modelLabel && !block.modelLabel ? { modelLabel } : {})
    }
  })
}

export function collectAssistantTextForTurn(
  blocks: ChatBlock[],
  userBlockId: string,
  liveAssistant: string
): string {
  const userIndex = blocks.findIndex((block) => block.kind === 'user' && block.id === userBlockId)
  if (userIndex < 0) return liveAssistant.trim()
  const parts: string[] = []
  for (let index = userIndex + 1; index < blocks.length; index += 1) {
    const block = blocks[index]
    if (block.kind === 'user') break
    if (block.kind === 'assistant' && block.text.trim()) {
      parts.push(block.text.trim())
    }
  }
  if (liveAssistant.trim()) parts.push(liveAssistant.trim())
  return parts.join('\n\n').trim()
}

export function upsertFinalAnswerBlock(
  blocks: ChatBlock[],
  itemId: string,
  text: string,
  createdAt?: string
): ChatBlock[] {
  const trimmed = text.trim()
  if (!trimmed) return blocks
  const withoutReasoning = blocks.filter(
    (block) => !(block.kind === 'reasoning' && block.id === itemId)
  )
  const nextBlock: ChatBlock = {
    kind: 'assistant',
    id: itemId,
    createdAt: createdAt ?? new Date().toISOString(),
    text: trimmed,
    agentSegment: 'final_answer'
  }
  const existingIdx = withoutReasoning.findIndex(
    (block) => block.kind === 'assistant' && block.id === itemId
  )
  if (existingIdx >= 0) {
    const next = [...withoutReasoning]
    next[existingIdx] = { ...withoutReasoning[existingIdx], ...nextBlock }
    return next
  }
  return [...withoutReasoning, nextBlock]
}

export function clearedThreadSelection(): Pick<
  ChatState,
  | 'activeThreadId'
  | 'activeThreadWarmup'
  | 'blocks'
  | 'lastSeq'
  | 'liveReasoning'
  | 'liveAssistant'
  | 'busy'
  | 'currentTurnId'
  | 'currentTurnUserId'
  | 'turnStartedAtByUserId'
  | 'turnDurationByUserId'
  | 'turnReasoningFirstAtByUserId'
  | 'turnReasoningLastAtByUserId'
  | 'inspectorSelectedId'
  | 'gitCommitSelectionKey'
  | 'gitCommitSelectedPaths'
  | 'queuedMessages'
  | 'scrollToBlockId'
  | 'activePlugin'
> {
  return {
    activeThreadId: null,
    activeThreadWarmup: { threadId: null, status: 'idle' },
    blocks: [],
    lastSeq: 0,
    liveReasoning: '',
    liveAssistant: '',
    busy: false,
    currentTurnId: null,
    currentTurnUserId: null,
    turnStartedAtByUserId: {},
    turnDurationByUserId: {},
    turnReasoningFirstAtByUserId: {},
    turnReasoningLastAtByUserId: {},
    inspectorSelectedId: null,
    gitCommitSelectionKey: null,
    gitCommitSelectedPaths: [],
    queuedMessages: [],
    scrollToBlockId: null,
    activePlugin: null
  }
}

export async function findReusableEmptyThreadId(
  state: ChatState,
  provider: ThreadDetailProviderLike,
  workspaceRoot: string
): Promise<string | null> {
  const normalizedWorkspace = normalizeWorkspaceRoot(workspaceRoot)
  if (!normalizedWorkspace) return null

  const activeThread = state.activeThreadId
    ? state.threads.find((thread) => thread.id === state.activeThreadId)
    : null
  if (
    activeThread &&
    normalizeWorkspaceRoot(activeThread.workspace) === normalizedWorkspace &&
    !threadHasUserMessage(state.blocks)
  ) {
    return activeThread.id
  }

  const candidates = state.threads
    .filter(
      (thread) =>
        thread.id !== activeThread?.id &&
        normalizeWorkspaceRoot(thread.workspace) === normalizedWorkspace
    )
    .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))

  for (const thread of candidates) {
    try {
      const { blocks } = await provider.getThreadDetail(thread.id)
      if (!threadHasUserMessage(blocks)) return thread.id
    } catch {
      /* ignore and keep checking other candidates */
    }
  }

  return null
}

function runtimeStatusLooksRunning(status?: string): boolean {
  const normalized = status?.trim().toLowerCase()
  return normalized === 'running'
    || normalized === 'in_progress'
    || normalized === 'queued'
    || normalized === 'started'
}

function threadHasUserMessage(blocks: ChatBlock[]): boolean {
  return blocks.some((block) => block.kind === 'user')
}
