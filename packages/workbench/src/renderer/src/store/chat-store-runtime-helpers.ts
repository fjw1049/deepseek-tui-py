import type {
  ChatBlock,
  UserInputQuestion,
  UserMessageEventPayload
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
  /** Present when a detached durable task bridged the approval here. */
  taskId?: string
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
  taskId?: string
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
      status: 'pending',
      ...(item.taskId ? { taskId: item.taskId } : {})
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
      status: 'pending',
      ...(item.taskId ? { taskId: item.taskId } : {})
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
  listThreads?: () => Promise<ChatState['threads']>
}

export function hasPendingRuntimeWork(block: ChatBlock): boolean {
  if (block.kind === 'tool') return block.status === 'running'
  if (block.kind === 'approval') return block.status === 'pending'
  if (block.kind === 'evolution') return block.status === 'pending'
  if (block.kind === 'user_input') return block.status === 'pending'
  if (block.kind === 'subagent') {
    return block.status === 'pending' || block.status === 'running'
  }
  return false
}

/**
 * After an interrupt (or force-clear), mark in-flight tools/subagents
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
    ...(ev.modelLabel ? { modelLabel: ev.modelLabel } : {}),
    ...(ev.turnId ? { turnId: ev.turnId } : {})
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
  modelLabel?: string,
  turnId?: string
): ChatBlock[] {
  return blocks.map((block) => {
    if (block.kind !== 'user' || block.id !== optimisticId) return block
    return {
      ...block,
      id: runtimeId,
      ...(fallbackText && !block.text.trim() ? { text: fallbackText } : {}),
      ...(modelLabel && !block.modelLabel ? { modelLabel } : {}),
      ...(turnId ? { turnId } : {})
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
  | 'lastCompletedTurnId'
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
  | 'turnDiffByTurnId'
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
    lastCompletedTurnId: null,
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
    activePlugin: null,
    turnDiffByTurnId: {}
  }
}

export async function findReusableEmptyThreadId(
  state: ChatState,
  provider: ThreadDetailProviderLike,
  workspaceRoot: string
): Promise<string | null> {
  const normalizedWorkspace = normalizeWorkspaceRoot(workspaceRoot)
  if (!normalizedWorkspace) return null

  // Another window/runtime may have published or blocked this task since the
  // local sidebar snapshot was received. Refresh the lightweight summaries
  // before deciding that an empty task is safe to reuse.
  let threads = state.threads
  if (provider.listThreads) {
    try {
      const fresh = await provider.listThreads()
      const freshById = new Map(fresh.map((thread) => [thread.id, thread]))
      threads = state.threads.map((thread) => freshById.get(thread.id) ?? thread)
    } catch {
      /* fall back to the local snapshot; the runtime start guard stays final */
    }
  }

  const activeThread = state.activeThreadId
    ? threads.find((thread) => thread.id === state.activeThreadId)
    : null
  if (
    activeThread &&
    normalizeWorkspaceRoot(activeThread.workspace) === normalizedWorkspace &&
    !threadHasUnresolvedPublishState(activeThread) &&
    !threadHasUserMessage(state.blocks)
  ) {
    return activeThread.id
  }

  const candidates = threads
    .filter(
      (thread) =>
        thread.id !== activeThread?.id &&
        normalizeWorkspaceRoot(thread.workspace) === normalizedWorkspace &&
        !threadHasUnresolvedPublishState(thread)
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

function threadHasUnresolvedPublishState(thread: ChatState['threads'][number]): boolean {
  return Boolean(
    thread.publishPending ||
    thread.publishBlocked ||
    thread.publishIssue != null ||
    (thread.publishConflicts?.length ?? 0) > 0
  )
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
