/** Sub-agent mailbox card state (mirrors TUI DelegateCard / FanoutCard). */

export type SubagentLifecycle = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export type MailboxMessageJson = {
  kind: string
  agent_id: string
  agent_type?: string | null
  status?: string | null
  tool_name?: string | null
  step?: number | null
  ok?: boolean | null
  parent_id?: string | null
  summary?: string | null
  error?: string | null
}

export type DelegateCardState = {
  cardKind: 'delegate'
  agentId: string
  agentType: string
  status: SubagentLifecycle
  summary?: string
  actions: string[]
  truncated: boolean
}

export type FanoutWorkerState = {
  id: string
  status: SubagentLifecycle
}

export type FanoutCardState = {
  cardKind: 'fanout'
  agentId: string
  dispatchKind: string
  workers: FanoutWorkerState[]
}

export type SubagentCardState = DelegateCardState | FanoutCardState

const DELEGATE_MAX_ACTIONS = 3

const FANOUT_AGENT_TYPES = new Set(['rlm', 'fanout', 'swarm', 'agent_swarm'])

export function isFanoutAgentType(agentType: string | null | undefined): boolean {
  if (!agentType) return false
  const normalized = agentType.trim().toLowerCase()
  return FANOUT_AGENT_TYPES.has(normalized) || normalized.includes('fanout')
}

function lifecycleFromKind(kind: string): SubagentLifecycle | null {
  switch (kind) {
    case 'started':
    case 'progress':
    case 'tool_call_started':
      return 'running'
    case 'completed':
      return 'completed'
    case 'failed':
      return 'failed'
    case 'cancelled':
      return 'cancelled'
    default:
      return null
  }
}

export function createDelegateCard(agentId: string, agentType: string): DelegateCardState {
  return {
    cardKind: 'delegate',
    agentId,
    agentType,
    status: 'pending',
    actions: [],
    truncated: false
  }
}

export function createFanoutCard(agentId: string, dispatchKind: string): FanoutCardState {
  return {
    cardKind: 'fanout',
    agentId,
    dispatchKind,
    workers: []
  }
}

export function applyMailboxToDelegate(
  card: DelegateCardState,
  msg: MailboxMessageJson
): DelegateCardState | null {
  if (msg.agent_id !== card.agentId) return null
  const next = { ...card, actions: [...card.actions] }
  switch (msg.kind) {
    case 'started':
      next.status = 'running'
      break
    case 'progress':
      next.status = 'running'
      if (msg.status) {
        next.actions.push(msg.status)
        if (next.actions.length > DELEGATE_MAX_ACTIONS) {
          next.actions.shift()
          next.truncated = true
        }
      }
      break
    case 'tool_call_started':
      next.actions.push(`[${msg.step ?? '?'}] ${msg.tool_name ?? 'tool'} started`)
      if (next.actions.length > DELEGATE_MAX_ACTIONS) {
        next.actions.shift()
        next.truncated = true
      }
      break
    case 'tool_call_completed': {
      const outcome = msg.ok ? 'ok' : 'failed'
      next.actions.push(`[${msg.step ?? '?'}] ${msg.tool_name ?? 'tool'} ${outcome}`)
      if (next.actions.length > DELEGATE_MAX_ACTIONS) {
        next.actions.shift()
        next.truncated = true
      }
      break
    }
    case 'completed':
      next.status = 'completed'
      next.summary = msg.summary ?? undefined
      break
    case 'failed':
      next.status = 'failed'
      next.summary = msg.error ?? undefined
      break
    case 'cancelled':
      next.status = 'cancelled'
      break
    default:
      return null
  }
  return next
}

function upsertWorker(workers: FanoutWorkerState[], id: string, status: SubagentLifecycle): FanoutWorkerState[] {
  const idx = workers.findIndex((w) => w.id === id)
  if (idx >= 0) {
    const copy = [...workers]
    copy[idx] = { id, status }
    return copy
  }
  return [...workers, { id, status }]
}

export function applyMailboxToFanout(
  card: FanoutCardState,
  msg: MailboxMessageJson
): FanoutCardState | null {
  const next = { ...card, workers: [...card.workers] }
  const agentId = msg.agent_id
  switch (msg.kind) {
    case 'started':
      next.workers = upsertWorker(next.workers, agentId, 'running')
      break
    case 'progress':
    case 'tool_call_started':
      next.workers = upsertWorker(next.workers, agentId, 'running')
      break
    case 'tool_call_completed':
      return next
    case 'completed':
      next.workers = upsertWorker(next.workers, agentId, 'completed')
      break
    case 'failed':
      next.workers = upsertWorker(next.workers, agentId, 'failed')
      break
    case 'cancelled':
      next.workers = upsertWorker(next.workers, agentId, 'cancelled')
      break
    case 'child_spawned':
      next.workers = upsertWorker(next.workers, agentId, 'pending')
      break
    default:
      return null
  }
  return next
}

// Lifecycle/progress kinds that may bootstrap a delegate card on their own. We
// can join a sub-agent's mailbox stream mid-flight (SSE reconnect with
// `since_seq` past the `started` event), so requiring `started` to create a card
// would silently drop every later message and the card would never appear.
const CARD_BOOTSTRAP_KINDS = new Set([
  'started',
  'progress',
  'tool_call_started',
  'tool_call_completed',
  'completed',
  'failed',
  'cancelled'
])

function findOwningFanoutId(
  cards: Record<string, SubagentCardState>,
  agentId: string
): string | null {
  for (const [id, card] of Object.entries(cards)) {
    if (card.cardKind === 'fanout' && card.workers.some((w) => w.id === agentId)) {
      return id
    }
  }
  return null
}

export function applyMailboxMessage(
  cards: Record<string, SubagentCardState>,
  msg: MailboxMessageJson
): Record<string, SubagentCardState> {
  const agentId = msg.agent_id
  let card = cards[agentId]
  // Route worker-level messages to the fanout that already owns them so they
  // update the parent card instead of spawning a stray standalone delegate.
  if (!card) {
    const ownerId = findOwningFanoutId(cards, agentId)
    if (ownerId) {
      const updated = applyMailboxToFanout(cards[ownerId] as FanoutCardState, msg)
      return updated ? { ...cards, [ownerId]: updated } : cards
    }
  }
  if (!card && CARD_BOOTSTRAP_KINDS.has(msg.kind)) {
    if (isFanoutAgentType(msg.agent_type)) {
      card = createFanoutCard(agentId, msg.agent_type ?? 'fanout')
    } else {
      // Bootstrapped mid-stream cards start as running; a terminal first message
      // (completed/failed/cancelled) is corrected by applyMailboxToDelegate below.
      card = { ...createDelegateCard(agentId, msg.agent_type ?? 'general'), status: 'running' }
    }
  }
  if (!card) {
    if (msg.kind === 'child_spawned' && msg.parent_id) {
      const parent = cards[msg.parent_id]
      if (parent?.cardKind === 'fanout') {
        const updated = applyMailboxToFanout(parent, msg)
        if (updated) return { ...cards, [msg.parent_id]: updated }
      }
    }
    return cards
  }
  const updated =
    card.cardKind === 'fanout'
      ? applyMailboxToFanout(card, msg)
      : applyMailboxToDelegate(card, msg)
  if (!updated) return cards
  return { ...cards, [agentId]: updated }
}

export function fanoutAggregateStatus(card: FanoutCardState): SubagentLifecycle {
  if (card.workers.length === 0) return 'pending'
  if (card.workers.some((w) => w.status === 'failed')) return 'failed'
  if (card.workers.some((w) => w.status === 'running' || w.status === 'pending')) {
    return 'running'
  }
  if (card.workers.every((w) => w.status === 'completed')) return 'completed'
  if (card.workers.every((w) => w.status === 'cancelled')) return 'cancelled'
  // Mixed terminal (e.g. 4 completed + 1 cancelled after workflow timeout):
  // never report "running" — that stuck the composer behind a fake busy turn.
  return 'cancelled'
}

export function cardLifecycle(card: SubagentCardState): SubagentLifecycle {
  if (card.cardKind === 'delegate') return card.status
  return fanoutAggregateStatus(card)
}

import type { ChatBlock } from '../agent/types'

export function subagentCardsFromBlocks(blocks: ChatBlock[]): Record<string, SubagentCardState> {
  const out: Record<string, SubagentCardState> = {}
  for (const block of blocks) {
    if (block.kind !== 'subagent') continue
    if (block.cardKind === 'delegate') {
      out[block.agentId] = {
        cardKind: 'delegate',
        agentId: block.agentId,
        agentType: block.agentType,
        status: block.status,
        summary: block.summary,
        actions: block.actions ?? [],
        truncated: block.truncated ?? false
      }
    } else {
      out[block.agentId] = {
        cardKind: 'fanout',
        agentId: block.agentId,
        dispatchKind: block.agentType,
        workers: block.workers ?? []
      }
    }
  }
  return out
}

export function subagentBlockFromCard(card: SubagentCardState, createdAt?: string): ChatBlock {
  const status = cardLifecycle(card)
  if (card.cardKind === 'delegate') {
    return {
      kind: 'subagent',
      id: `subagent-${card.agentId}`,
      createdAt,
      cardKind: 'delegate',
      agentId: card.agentId,
      agentType: card.agentType,
      status,
      summary: card.summary,
      actions: card.actions,
      truncated: card.truncated
    }
  }
  return {
    kind: 'subagent',
    id: `subagent-${card.agentId}`,
    createdAt,
    cardKind: 'fanout',
    agentId: card.agentId,
    agentType: card.dispatchKind,
    status,
    workers: card.workers
  }
}

export function cardLabel(card: SubagentCardState): string {
  if (card.cardKind === 'delegate') {
    return `${card.agentType} · ${card.agentId.slice(0, 8)}`
  }
  const done = card.workers.filter((w) => w.status === 'completed').length
  const running = card.workers.filter((w) => w.status === 'running').length
  const failed = card.workers.filter((w) => w.status === 'failed').length
  return `${card.dispatchKind} · ${done} done · ${running} running · ${failed} failed`
}

/**
 * When the owning turn is no longer active, any sub-agent still showing
 * pending/running is a stale UI card (terminal mailbox never persisted).
 * Force them to cancelled so the composer is not stuck "busy" forever.
 */
export function finalizeOrphanSubagentBlocks(blocks: ChatBlock[]): ChatBlock[] {
  let changed = false
  const next = blocks.map((block) => {
    if (block.kind !== 'subagent') return block
    if (block.cardKind === 'delegate') {
      if (block.status !== 'pending' && block.status !== 'running') return block
      changed = true
      return { ...block, status: 'cancelled' as const }
    }
    const workers = block.workers ?? []
    let workersChanged = false
    const nextWorkers = workers.map((worker) => {
      if (worker.status !== 'pending' && worker.status !== 'running') return worker
      workersChanged = true
      return { ...worker, status: 'cancelled' as const }
    })
    if (!workersChanged && block.status !== 'pending' && block.status !== 'running') {
      return block
    }
    changed = true
    const nextBlock = {
      ...block,
      workers: nextWorkers,
      status: cardLifecycle({
        cardKind: 'fanout',
        agentId: block.agentId,
        dispatchKind: block.agentType,
        workers: nextWorkers
      })
    }
    return nextBlock
  })
  return changed ? next : blocks
}
