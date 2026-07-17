/** Sub-agent mailbox card state (mirrors TUI DelegateCard / FanoutCard). */

import { collapseStepFlowProbes } from './step-flow-collapse'
import { buildStepIntent } from './step-intent'

export type SubagentLifecycle = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export type MailboxMessageJson = {
  kind: string
  agent_id: string
  /** Monotonic mailbox envelope seq (0/absent for synthesized reconcile events). */
  seq?: number | null
  agent_type?: string | null
  status?: string | null
  tool_name?: string | null
  step?: number | null
  tool_call_id?: string | null
  ok?: boolean | null
  parent_id?: string | null
  summary?: string | null
  error?: string | null
  input_summary?: string | null
  output_summary?: string | null
}

export type SubagentStepKind =
  | 'started'
  | 'progress'
  | 'tool'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type SubagentStepState = {
  id: string
  kind: SubagentStepKind
  step?: number | null
  toolName?: string | null
  /** For tool steps: null while running, then true/false when completed. */
  ok?: boolean | null
  label: string
  input?: string | null
  output?: string | null
}

export type DelegateCardState = {
  cardKind: 'delegate'
  agentId: string
  agentType: string
  status: SubagentLifecycle
  summary?: string
  /** Short preview lines for compact surfaces (last N step labels). */
  actions: string[]
  truncated: boolean
  steps: SubagentStepState[]
  parentId?: string | null
  childIds: string[]
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
  /** Per-worker step history (fanout workers are not separate blocks). */
  workerSteps: Record<string, SubagentStepState[]>
  parentId?: string | null
  childIds: string[]
}

export type SubagentCardState = DelegateCardState | FanoutCardState

/** Compact action preview only — full history lives in ``steps``. */
const DELEGATE_MAX_ACTIONS = 3
const DELEGATE_MAX_STEPS = 200

const FANOUT_AGENT_TYPES = new Set(['rlm', 'fanout', 'swarm', 'agent_swarm'])

export function isFanoutAgentType(agentType: string | null | undefined): boolean {
  if (!agentType) return false
  const normalized = agentType.trim().toLowerCase()
  return FANOUT_AGENT_TYPES.has(normalized) || normalized.includes('fanout')
}

export function createDelegateCard(agentId: string, agentType: string): DelegateCardState {
  return {
    cardKind: 'delegate',
    agentId,
    agentType,
    status: 'pending',
    actions: [],
    truncated: false,
    steps: [],
    parentId: null,
    childIds: []
  }
}

export function createFanoutCard(agentId: string, dispatchKind: string): FanoutCardState {
  return {
    cardKind: 'fanout',
    agentId,
    dispatchKind,
    workers: [],
    workerSteps: {},
    parentId: null,
    childIds: []
  }
}

function pushUniqueChild(childIds: string[], childId: string): string[] {
  if (childIds.includes(childId)) return childIds
  return [...childIds, childId]
}

function syncActionPreview(steps: SubagentStepState[]): {
  actions: string[]
  truncated: boolean
} {
  const labels = steps.map((s) => s.label)
  if (labels.length <= DELEGATE_MAX_ACTIONS) {
    return { actions: labels, truncated: false }
  }
  return {
    actions: labels.slice(-DELEGATE_MAX_ACTIONS),
    truncated: true
  }
}

function capSteps(steps: SubagentStepState[]): SubagentStepState[] {
  if (steps.length <= DELEGATE_MAX_STEPS) return steps
  return steps.slice(-DELEGATE_MAX_STEPS)
}

function toolStepId(msg: MailboxMessageJson): string {
  // Prefer the provider tool-call id: parallel same-name calls in one round
  // share the same `step` number, so `tool-${step}-${name}` collides and one
  // call would silently overwrite the other.
  if (msg.tool_call_id) return `tool-${msg.tool_call_id}`
  return `tool-${msg.step ?? '?'}-${msg.tool_name ?? 'tool'}`
}

function fallbackToolStepId(msg: MailboxMessageJson): string {
  return `tool-${msg.step ?? '?'}-${msg.tool_name ?? 'tool'}`
}

/**
 * Locate an existing tool row to upsert. Prefer exact id (tool_call_id), then
 * a provisional fallback row for the same step+name still running — so a
 * started-without-id / completed-with-id pair does not spawn a duplicate rail.
 */
function findToolStepIndex(
  steps: SubagentStepState[],
  msg: MailboxMessageJson
): number {
  const id = toolStepId(msg)
  const byId = steps.findIndex((s) => s.id === id && s.kind === 'tool')
  if (byId >= 0) return byId

  if (msg.tool_call_id) {
    const fallback = fallbackToolStepId(msg)
    const byFallback = steps.findIndex(
      (s) => s.id === fallback && s.kind === 'tool' && s.ok === null
    )
    if (byFallback >= 0) return byFallback
  }

  return -1
}

/**
 * Lifecycle/progress step ids must stay unique within a card even after
 * `capSteps` truncation (steps.length stops growing at the cap, so indexing
 * off it repeats ids and breaks React keys). Prefer the monotonic mailbox
 * seq; fall back to max existing numeric suffix + 1 when seq is absent
 * (synthesized reconcile envelopes carry seq=0).
 */
function nextStepId(
  kind: string,
  steps: SubagentStepState[],
  seq?: number | null
): string {
  if (seq != null && seq > 0) return `${kind}-${seq}`
  let max = 0
  for (const s of steps) {
    const match = /-(\d+)$/.exec(s.id)
    if (match) max = Math.max(max, Number(match[1]))
  }
  return `${kind}-${max + 1}`
}

function appendOrUpdateToolStep(
  steps: SubagentStepState[],
  msg: MailboxMessageJson,
  phase: 'started' | 'completed'
): SubagentStepState[] {
  const toolName = msg.tool_name ?? 'tool'
  const stepNum = msg.step ?? null
  const id = toolStepId(msg)
  const next = [...steps]
  const idx = findToolStepIndex(next, msg)
  const input = msg.input_summary ?? (idx >= 0 ? next[idx]!.input : null) ?? null
  const intent = buildStepIntent({ toolName, inputSummary: input })
  if (phase === 'started') {
    const row: SubagentStepState = {
      id,
      kind: 'tool',
      step: stepNum,
      toolName,
      ok: null,
      label: intent.label,
      input,
      output: null
    }
    if (idx >= 0) {
      next[idx] = {
        ...next[idx]!,
        ...row,
        // Promote provisional fallback ids to tool_call_id when it arrives.
        id,
        input: msg.input_summary ?? next[idx]!.input ?? null,
        label: buildStepIntent({
          toolName,
          inputSummary: msg.input_summary ?? next[idx]!.input
        }).label
      }
    } else {
      next.push(row)
    }
    return capSteps(next)
  }
  const row: SubagentStepState = {
    id,
    kind: 'tool',
    step: stepNum,
    toolName,
    ok: msg.ok ?? false,
    label: intent.label,
    input,
    output: msg.output_summary ?? null
  }
  if (idx >= 0) {
    const mergedInput = msg.input_summary ?? next[idx]!.input ?? null
    next[idx] = {
      ...next[idx]!,
      ...row,
      id,
      input: mergedInput,
      output: msg.output_summary ?? next[idx]!.output ?? null,
      label: buildStepIntent({ toolName, inputSummary: mergedInput }).label
    }
  } else {
    next.push(row)
  }
  return capSteps(next)
}

function appendLifecycleStep(
  steps: SubagentStepState[],
  kind: Exclude<SubagentStepKind, 'tool' | 'progress'>,
  label: string,
  output?: string | null,
  seq?: number | null
): SubagentStepState[] {
  // Avoid duplicate terminal/start markers of the same kind at the tail.
  const last = steps[steps.length - 1]
  if (last && last.kind === kind && last.label === label) return steps
  return capSteps([
    ...steps,
    {
      id: nextStepId(kind, steps, seq),
      kind,
      label,
      output: output ?? null
    }
  ])
}

export function applyMailboxToDelegate(
  card: DelegateCardState,
  msg: MailboxMessageJson
): DelegateCardState | null {
  if (msg.agent_id !== card.agentId && msg.kind !== 'child_spawned') return null
  if (msg.kind === 'child_spawned') {
    if (msg.parent_id !== card.agentId) return null
    return {
      ...card,
      childIds: pushUniqueChild(card.childIds, msg.agent_id)
    }
  }

  let steps = [...card.steps]
  let status = card.status
  let summary = card.summary

  switch (msg.kind) {
    case 'started':
      status = 'running'
      steps = appendLifecycleStep(steps, 'started', '● running', undefined, msg.seq)
      break
    case 'progress':
      status = 'running'
      if (msg.status) {
        steps = capSteps([
          ...steps,
          {
            id: nextStepId('progress', steps, msg.seq),
            kind: 'progress',
            label: msg.status,
            output: msg.status
          }
        ])
      }
      break
    case 'tool_call_started':
      status = 'running'
      steps = appendOrUpdateToolStep(steps, msg, 'started')
      break
    case 'tool_call_completed':
      status = 'running'
      steps = appendOrUpdateToolStep(steps, msg, 'completed')
      break
    case 'completed':
      status = 'completed'
      summary = msg.summary ?? undefined
      steps = appendLifecycleStep(steps, 'completed', '✓ completed', msg.summary, msg.seq)
      break
    case 'failed':
      status = 'failed'
      summary = msg.error ?? undefined
      steps = appendLifecycleStep(steps, 'failed', '✗ failed', msg.error, msg.seq)
      break
    case 'cancelled':
      status = 'cancelled'
      steps = appendLifecycleStep(steps, 'cancelled', '− cancelled', undefined, msg.seq)
      break
    default:
      return null
  }

  const preview = syncActionPreview(steps)
  return {
    ...card,
    status,
    summary,
    steps,
    actions: preview.actions,
    truncated: preview.truncated
  }
}

function upsertWorker(
  workers: FanoutWorkerState[],
  id: string,
  status: SubagentLifecycle
): FanoutWorkerState[] {
  const idx = workers.findIndex((w) => w.id === id)
  if (idx >= 0) {
    const copy = [...workers]
    copy[idx] = { id, status }
    return copy
  }
  return [...workers, { id, status }]
}

function applyStepsToWorker(
  workerSteps: Record<string, SubagentStepState[]>,
  workerId: string,
  mutate: (steps: SubagentStepState[]) => SubagentStepState[]
): Record<string, SubagentStepState[]> {
  const prev = workerSteps[workerId] ?? []
  return { ...workerSteps, [workerId]: mutate(prev) }
}

export function applyMailboxToFanout(
  card: FanoutCardState,
  msg: MailboxMessageJson
): FanoutCardState | null {
  const next: FanoutCardState = {
    ...card,
    workers: [...card.workers],
    workerSteps: { ...card.workerSteps },
    childIds: [...card.childIds]
  }
  const agentId = msg.agent_id

  switch (msg.kind) {
    case 'started':
      next.workers = upsertWorker(next.workers, agentId, 'running')
      next.childIds = pushUniqueChild(next.childIds, agentId)
      next.workerSteps = applyStepsToWorker(next.workerSteps, agentId, (steps) =>
        appendLifecycleStep(steps, 'started', '● running', undefined, msg.seq)
      )
      break
    case 'progress':
      next.workers = upsertWorker(next.workers, agentId, 'running')
      if (msg.status) {
        next.workerSteps = applyStepsToWorker(next.workerSteps, agentId, (steps) =>
          capSteps([
            ...steps,
            {
              id: nextStepId('progress', steps, msg.seq),
              kind: 'progress',
              label: msg.status!,
              output: msg.status
            }
          ])
        )
      }
      break
    case 'tool_call_started':
      next.workers = upsertWorker(next.workers, agentId, 'running')
      next.workerSteps = applyStepsToWorker(next.workerSteps, agentId, (steps) =>
        appendOrUpdateToolStep(steps, msg, 'started')
      )
      break
    case 'tool_call_completed':
      next.workerSteps = applyStepsToWorker(next.workerSteps, agentId, (steps) =>
        appendOrUpdateToolStep(steps, msg, 'completed')
      )
      break
    case 'completed':
      next.workers = upsertWorker(next.workers, agentId, 'completed')
      next.workerSteps = applyStepsToWorker(next.workerSteps, agentId, (steps) =>
        appendLifecycleStep(steps, 'completed', '✓ completed', msg.summary, msg.seq)
      )
      break
    case 'failed':
      next.workers = upsertWorker(next.workers, agentId, 'failed')
      next.workerSteps = applyStepsToWorker(next.workerSteps, agentId, (steps) =>
        appendLifecycleStep(steps, 'failed', '✗ failed', msg.error, msg.seq)
      )
      break
    case 'cancelled':
      next.workers = upsertWorker(next.workers, agentId, 'cancelled')
      next.workerSteps = applyStepsToWorker(next.workerSteps, agentId, (steps) =>
        appendLifecycleStep(steps, 'cancelled', '− cancelled', undefined, msg.seq)
      )
      break
    case 'child_spawned':
      next.workers = upsertWorker(next.workers, agentId, 'pending')
      next.childIds = pushUniqueChild(next.childIds, agentId)
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

function linkChildToParent(
  cards: Record<string, SubagentCardState>,
  parentId: string,
  childId: string
): Record<string, SubagentCardState> {
  const parent = cards[parentId]
  if (!parent) return cards
  if (parent.cardKind === 'fanout') {
    const updated = applyMailboxToFanout(parent, {
      kind: 'child_spawned',
      agent_id: childId,
      parent_id: parentId
    })
    return updated ? { ...cards, [parentId]: updated } : cards
  }
  const updated = applyMailboxToDelegate(parent, {
    kind: 'child_spawned',
    agent_id: childId,
    parent_id: parentId
  })
  return updated ? { ...cards, [parentId]: updated } : cards
}

export function applyMailboxMessage(
  cards: Record<string, SubagentCardState>,
  msg: MailboxMessageJson
): Record<string, SubagentCardState> {
  let nextCards = cards
  const agentId = msg.agent_id

  // Parent→child edge: always wire the parent. Fanout parents keep children as
  // workers only (no extra timeline cards). Delegate parents get a child card
  // so the detail dialog can show a nested step rail.
  if (msg.kind === 'child_spawned' && msg.parent_id) {
    nextCards = linkChildToParent(nextCards, msg.parent_id, agentId)
    const parent = nextCards[msg.parent_id]
    if (parent?.cardKind === 'fanout') {
      return nextCards
    }
    const existing = nextCards[agentId]
    if (!existing) {
      const child = createDelegateCard(agentId, msg.agent_type ?? 'general')
      child.parentId = msg.parent_id
      child.status = 'pending'
      nextCards = { ...nextCards, [agentId]: child }
    } else if (existing.cardKind === 'delegate' && !existing.parentId) {
      nextCards = {
        ...nextCards,
        [agentId]: { ...existing, parentId: msg.parent_id }
      }
    } else if (existing.cardKind === 'fanout' && !existing.parentId) {
      nextCards = {
        ...nextCards,
        [agentId]: { ...existing, parentId: msg.parent_id }
      }
    }
    return nextCards
  }

  let card = nextCards[agentId]
  // Route worker-level messages to the fanout that already owns them so they
  // update the parent card instead of spawning a stray standalone delegate.
  if (!card) {
    const ownerId = findOwningFanoutId(nextCards, agentId)
    if (ownerId) {
      const updated = applyMailboxToFanout(nextCards[ownerId] as FanoutCardState, msg)
      return updated ? { ...nextCards, [ownerId]: updated } : nextCards
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
  if (!card) return nextCards

  const updated =
    card.cardKind === 'fanout'
      ? applyMailboxToFanout(card, msg)
      : applyMailboxToDelegate(card, msg)
  if (!updated) return nextCards
  return { ...nextCards, [agentId]: updated }
}

export type MailboxApplyResult = {
  cards: Record<string, SubagentCardState>
  /**
   * Agent ids whose card object actually changed. Writers that rebuild the
   * card map from blocks on every event (chat-store live path) must upsert
   * the blocks for ALL of these — e.g. `child_spawned` also rewrites the
   * parent card's childIds, worker events rewrite the owning fanout — or the
   * change is silently dropped on the next event's rebuild.
   */
  touched: string[]
}

export function applyMailboxMessageTouched(
  cards: Record<string, SubagentCardState>,
  msg: MailboxMessageJson
): MailboxApplyResult {
  const next = applyMailboxMessage(cards, msg)
  const touched: string[] = []
  for (const [id, card] of Object.entries(next)) {
    if (cards[id] !== card) touched.push(id)
  }
  return { cards: next, touched }
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

import type { ChatBlock, SubagentStepBlock } from '../agent/types'

function stepsToBlock(steps: SubagentStepState[] | undefined): SubagentStepBlock[] | undefined {
  if (!steps || steps.length === 0) return undefined
  return steps.map((s) => ({
    id: s.id,
    kind: s.kind,
    step: s.step ?? null,
    toolName: s.toolName ?? null,
    ok: s.ok ?? null,
    label: s.label,
    input: s.input ?? null,
    output: s.output ?? null
  }))
}

function stepsFromBlock(steps: SubagentStepBlock[] | undefined): SubagentStepState[] {
  if (!steps) return []
  return steps.map((s) => ({
    id: s.id,
    kind: s.kind,
    step: s.step,
    toolName: s.toolName,
    ok: s.ok,
    label: s.label,
    input: s.input,
    output: s.output
  }))
}

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
        truncated: block.truncated ?? false,
        steps: stepsFromBlock(block.steps),
        parentId: block.parentId ?? null,
        childIds: block.childIds ?? []
      }
    } else {
      const workerSteps: Record<string, SubagentStepState[]> = {}
      for (const [id, steps] of Object.entries(block.workerSteps ?? {})) {
        workerSteps[id] = stepsFromBlock(steps)
      }
      out[block.agentId] = {
        cardKind: 'fanout',
        agentId: block.agentId,
        dispatchKind: block.agentType,
        workers: block.workers ?? [],
        workerSteps,
        parentId: block.parentId ?? null,
        childIds: block.childIds ?? (block.workers ?? []).map((w) => w.id)
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
      truncated: card.truncated,
      steps: stepsToBlock(card.steps),
      parentId: card.parentId ?? null,
      childIds: card.childIds
    }
  }
  const workerSteps: Record<string, SubagentStepBlock[]> = {}
  for (const [id, steps] of Object.entries(card.workerSteps)) {
    const mapped = stepsToBlock(steps)
    if (mapped) workerSteps[id] = mapped
  }
  return {
    kind: 'subagent',
    id: `subagent-${card.agentId}`,
    createdAt,
    cardKind: 'fanout',
    agentId: card.agentId,
    agentType: card.dispatchKind,
    status,
    workers: card.workers,
    workerSteps: Object.keys(workerSteps).length > 0 ? workerSteps : undefined,
    parentId: card.parentId ?? null,
    childIds: card.childIds
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
        workers: nextWorkers,
        workerSteps: {},
        childIds: []
      })
    }
    return nextBlock
  })
  return changed ? next : blocks
}

/**
 * Residual 'running' rows in a terminal card are stale, not live: map them to
 * a settled status so the UI stops pulsing. `completed` cards degrade to
 * 'info' (a properly finished tool call carries an ok value; an ok:null row
 * is just unfinished history), failure-ish terminals degrade to 'cancelled'.
 */
function terminalResidualStatus(cardStatus: string): 'info' | 'cancelled' | null {
  if (cardStatus === 'completed') return 'info'
  if (
    cardStatus === 'failed' ||
    cardStatus === 'cancelled' ||
    cardStatus === 'interrupted'
  ) {
    return 'cancelled'
  }
  return null
}

/** Convert stored steps into StepFlow rows (shared UI). */
export function subagentStepsToFlowItems(
  steps: SubagentStepState[] | SubagentStepBlock[] | undefined,
  depth = 0,
  /** Card lifecycle status; when terminal, residual 'running' rows degrade. */
  cardStatus?: string | null
): import('../components/chat/StepFlow').StepFlowItem[] {
  if (!steps || steps.length === 0) return []
  const residual = cardStatus ? terminalResidualStatus(cardStatus) : null
  // Tools that follow a round narration sit one level deeper so the rail reads
  // as knowledge → actions, not a flat tool log.
  let underNarration = false
  const mapped = steps.map((s) => {
    let status: import('../components/chat/StepFlow').StepFlowStatus = 'info'
    if (s.kind === 'tool') {
      if (s.ok === true) status = 'ok'
      else if (s.ok === false) status = 'failed'
      else status = 'running'
    } else if (s.kind === 'started') {
      status = 'running'
    } else if (s.kind === 'progress') {
      // Narration is a settled knowledge line, not a pulsing spinner.
      status = 'info'
      underNarration = true
    } else if (s.kind === 'completed') {
      status = 'completed'
      underNarration = false
    } else if (s.kind === 'failed') {
      status = 'failed'
      underNarration = false
    } else if (s.kind === 'cancelled') {
      status = 'cancelled'
      underNarration = false
    }
    if (status === 'running' && residual) status = residual

    if (s.kind === 'progress') {
      return {
        id: s.id,
        status,
        label: s.label,
        output: s.output,
        depth,
        variant: 'narration' as const
      }
    }

    if (s.kind === 'tool' && s.toolName) {
      const intent = buildStepIntent({
        toolName: s.toolName,
        inputSummary: s.input
      })
      const toolDepth = underNarration ? depth + 1 : depth
      return {
        id: s.id,
        status,
        label: intent.title,
        detail: intent.detail || undefined,
        meta: s.step != null ? `step ${s.step}` : undefined,
        input: s.input,
        output: s.output,
        depth: toolDepth,
        toolName: s.toolName
      }
    }

    // Lifecycle chrome (started / completed / …) stays at the base depth and
    // does not keep tools indented under a prior narration.
    if (s.kind !== 'tool') underNarration = false

    return {
      id: s.id,
      status,
      label: s.label,
      input: s.input,
      output: s.output,
      depth
    }
  })
  return collapseStepFlowProbes(mapped)
}
