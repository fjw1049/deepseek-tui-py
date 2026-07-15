import type {
  AgentProvider,
  AgentProviderId,
  ActivePluginMeta,
  ApprovalRequestPayload,
  ElevationRequestPayload,
  EvolutionProposalPayload,
  ChatBlock,
  NormalizedThread,
  ProcessIntentMeta,
  ThreadDeltaEvent,
  SubagentMailboxPayload,
  ThreadEventSink,
  ToolBlock,
  ToolItemKind,
  UserMessageEventPayload,
  UserInputAnswer,
  UserInputQuestion,
  UserInputRequestPayload,
  WorkflowProgressPayload
} from './types'
import type { AppSettingsV1 } from '@shared/app-settings'
import { unwrapClawRuntimePromptForDisplay, unwrapClawUserPromptForDisplay } from '@shared/app-settings'
import { extractDiffFilePath } from '../lib/diff-stats'
import {
  applyMailboxMessage,
  subagentBlockFromCard,
  type MailboxMessageJson,
  type SubagentCardState
} from '../lib/subagent-mailbox'
import {
  parseWorkflowProgressPayload,
  parseWorkflowSnapshot,
  workflowSnapshotFromToolMeta,
  workflowRunIdFromToolMeta
} from '../lib/workflow-snapshot'
import { upsertWorkflowBlock } from '../store/chat-store-runtime-helpers'

function emitApprovalFromSsePayload(
  sink: ThreadEventSink,
  payload: Record<string, unknown>,
  approvalId: string
): void {
  const req = approvalPayloadFromRecord({
    ...payload,
    approval_id: approvalId,
    id: approvalId
  })
  if (req) sink.onApproval(req)
}

function evolutionPayloadFromRecord(
  row: Record<string, unknown>
): EvolutionProposalPayload | null {
  const recordId = String(row.record_id ?? row.id ?? '')
  if (!recordId) return null
  return {
    recordId,
    kind: String(row.kind ?? 'unknown'),
    summary: String(row.summary ?? 'Experience evolution proposal'),
    assetPath:
      typeof row.asset_path === 'string' && row.asset_path.trim()
        ? row.asset_path.trim()
        : undefined
  }
}

function emitEvolutionFromSsePayload(
  sink: ThreadEventSink,
  payload: Record<string, unknown>,
  recordId: string
): void {
  const req = evolutionPayloadFromRecord({
    ...payload,
    record_id: recordId,
    id: recordId
  })
  if (req && sink.onEvolutionProposal) sink.onEvolutionProposal(req)
}

function elevationPayloadFromRecord(
  row: Record<string, unknown>
): ElevationRequestPayload | null {
  const elevationId = String(row.elevation_id ?? row.tool_call_id ?? row.id ?? '')
  if (!elevationId) return null
  return {
    elevationId,
    toolName: typeof row.tool_name === 'string' ? row.tool_name : undefined,
    reason: String(row.reason ?? row.description ?? 'Sandbox blocked this command'),
    elevationKind: String(row.elevation_kind ?? 'unknown'),
    commandPreview:
      typeof row.primary_preview === 'string' && row.primary_preview.trim()
        ? row.primary_preview.trim()
        : typeof row.command_preview === 'string' && row.command_preview.trim()
          ? row.command_preview.trim()
          : undefined
  }
}

function emitElevationFromSsePayload(
  sink: ThreadEventSink,
  payload: Record<string, unknown>,
  elevationId: string
): void {
  const req = elevationPayloadFromRecord({
    ...payload,
    elevation_id: elevationId,
    id: elevationId
  })
  if (req && sink.onElevation) sink.onElevation(req)
}

function approvalPayloadFromRecord(
  row: Record<string, unknown>
): ApprovalRequestPayload | null {
  const approvalId = String(row.approval_id ?? row.id ?? '')
  if (!approvalId) return null
  const impacts = Array.isArray(row.impacts)
    ? row.impacts.filter((line): line is string => typeof line === 'string' && line.trim().length > 0)
    : undefined
  const presentationRisk =
    typeof row.risk === 'string'
      ? row.risk
      : typeof row.presentation_risk === 'string'
        ? row.presentation_risk
        : undefined
  return {
    approvalId,
    summary: String(row.title ?? row.description ?? row.summary ?? 'Approval required'),
    inputSummary:
      typeof row.primary_preview === 'string' && row.primary_preview.trim()
        ? row.primary_preview.trim()
        : typeof row.input_summary === 'string' && row.input_summary.trim()
          ? row.input_summary.trim()
          : undefined,
    impacts: impacts?.length ? impacts : undefined,
    riskLevel: typeof row.risk_level === 'string' ? row.risk_level : undefined,
    presentationRisk,
    toolName: typeof row.tool_name === 'string' ? row.tool_name : undefined
  }
}

type ThreadRecordJson = {
  id: string
  created_at: string
  updated_at: string
  model: string
  workspace: string
  mode: string
  status?: string
  archived?: boolean
  title?: string | null
}

type TurnItemJson = {
  id: string
  turn_id?: string
  kind: string
  summary: string
  detail?: string | null
  status?: string
  metadata?: Record<string, unknown> | null
  artifact_refs?: string[]
  started_at?: string | null
  ended_at?: string | null
}

type TurnRecordJson = {
  id: string
  thread_id?: string
  status?: string
  item_ids?: string[]
  created_at?: string | null
  started_at?: string | null
  ended_at?: string | null
}

type ThreadDetailJson = {
  thread: ThreadRecordJson
  turns?: TurnRecordJson[]
  items: TurnItemJson[]
  latest_seq: number
}

type StartTurnResponseJson = {
  thread: ThreadRecordJson
  turn: { id: string; item_ids?: string[] }
}

type RuntimeErrorJson = {
  error?: string | { message?: string; status?: number }
  message?: string
}

type RuntimeExecutionFlags = {
  auto_approve: boolean
  trust_mode: boolean
}

const TOOL_ITEM_KINDS = new Set(['tool_call', 'command_execution', 'file_change'])
const REQUEST_USER_INPUT_TOOL = 'request_user_input'
/** Cap in-memory tool detail; full text is lazy-loaded via fetchItemDetail. ~8KB. */
const TOOL_DETAIL_MAX_CHARS = 8192

function titleFromThread(t: ThreadRecordJson): string {
  const raw = t.title?.trim()
  if (raw) return raw
  return t.id.slice(0, 8)
}

function toToolKind(kind: string): ToolItemKind | undefined {
  if (kind === 'tool_call' || kind === 'command_execution' || kind === 'file_change') {
    return kind
  }
  return undefined
}

function statusFromString(s: string | undefined): 'running' | 'success' | 'error' {
  if (s === 'failed' || s === 'canceled' || s === 'interrupted' || s === 'error') return 'error'
  if (s === 'in_progress' || s === 'queued' || s === 'started') return 'running'
  return 'success'
}

function displayModelFromUserMessageMeta(metadata: Record<string, unknown> | null | undefined): string | undefined {
  if (!metadata) return undefined
  const requested = typeof metadata.requested_model === 'string' ? metadata.requested_model.trim() : ''
  const effective = typeof metadata.effective_model === 'string' ? metadata.effective_model.trim() : ''
  const autoModel = metadata.auto_model === true
  if (!requested && !effective) return undefined
  const reqLower = requested.toLowerCase()
  if (autoModel && reqLower === 'auto') {
    if (effective && effective.toLowerCase() !== 'auto') {
      return `auto → ${effective}`
    }
    return 'auto'
  }
  if (requested && effective && requested !== effective) {
    return `${requested} → ${effective}`
  }
  return effective || requested || undefined
}

function deriveFilePath(item: TurnItemJson): string | undefined {
  const meta = (item.metadata ?? undefined) as Record<string, unknown> | undefined
  if (meta) {
    for (const k of ['path', 'file_path', 'filename', 'target']) {
      const v = meta[k]
      if (typeof v === 'string' && v.trim()) return v.trim()
    }
  }
  if (Array.isArray(item.artifact_refs) && item.artifact_refs.length > 0) {
    const first = item.artifact_refs[0]
    if (typeof first === 'string' && first.trim()) return first.trim()
  }
  return extractDiffFilePath(item.detail ?? item.summary)
}

/**
 * Fold a tool call's input arguments into its metadata as `tool_input` so the
 * UI can build a descriptor ("browse dir src/", "grep TODO"). The runtime emits
 * these args on item.started/completed under `payload.tool.input`, but they were
 * previously dropped — leaving rows that said only "browse dir" with no target.
 */
function metaWithToolInput(
  metadata: Record<string, unknown> | undefined,
  input: unknown
): Record<string, unknown> | undefined {
  if (input == null || typeof input !== 'object' || Array.isArray(input)) {
    return metadata
  }
  return { ...(metadata ?? {}), tool_input: input as Record<string, unknown> }
}

function deriveTurnId(item: TurnItemJson): string | undefined {
  if (typeof item.turn_id === 'string' && item.turn_id.trim()) return item.turn_id.trim()
  const meta = (item.metadata ?? undefined) as Record<string, unknown> | undefined
  const raw = meta?.turn_id
  return typeof raw === 'string' && raw.trim() ? raw.trim() : undefined
}

function readPayloadItem(payload: Record<string, unknown>): TurnItemJson | null {
  const it = payload.item as Record<string, unknown> | undefined
  if (!it || typeof it.id !== 'string') return null
  return {
    id: it.id,
    turn_id: typeof it.turn_id === 'string' ? it.turn_id : undefined,
    kind: String(it.kind ?? ''),
    summary: typeof it.summary === 'string' ? it.summary : '',
    detail: typeof it.detail === 'string' ? it.detail : null,
    status: typeof it.status === 'string' ? it.status : undefined,
    metadata: (it.metadata ?? null) as Record<string, unknown> | null,
    artifact_refs: Array.isArray(it.artifact_refs)
      ? (it.artifact_refs.filter((s) => typeof s === 'string') as string[])
      : [],
    started_at: typeof it.started_at === 'string' ? it.started_at : null,
    ended_at: typeof it.ended_at === 'string' ? it.ended_at : null
  }
}

function readPayloadTool(payload: Record<string, unknown>): {
  id?: string
  name?: string
  input?: unknown
} | null {
  const tool = payload.tool as Record<string, unknown> | undefined
  if (!tool || typeof tool !== 'object') return null
  return {
    id: typeof tool.id === 'string' && tool.id.trim() ? tool.id.trim() : undefined,
    name: typeof tool.name === 'string' && tool.name.trim() ? tool.name.trim() : undefined,
    input: tool.input
  }
}

function readUserInputQuestions(value: unknown): UserInputQuestion[] | null {
  if (!value) return null
  const rawQuestions = Array.isArray(value)
    ? value
    : typeof value === 'object'
      ? (value as Record<string, unknown>).questions
      : null
  if (!Array.isArray(rawQuestions) || rawQuestions.length === 0) return null
  const questions: UserInputQuestion[] = []
  for (const rawQuestion of rawQuestions) {
    if (!rawQuestion || typeof rawQuestion !== 'object') return null
    const q = rawQuestion as Record<string, unknown>
    const rawOptions = q.options
    if (!Array.isArray(rawOptions) || rawOptions.length === 0) return null
    const options = rawOptions
      .map((rawOption): { label: string; description: string } | null => {
        if (!rawOption || typeof rawOption !== 'object') return null
        const opt = rawOption as Record<string, unknown>
        const label = typeof opt.label === 'string' ? opt.label.trim() : ''
        const description = typeof opt.description === 'string' ? opt.description.trim() : ''
        if (!label) return null
        return { label, description: description || label }
      })
      .filter((opt): opt is { label: string; description: string } => opt != null)
    const header = typeof q.header === 'string' ? q.header.trim() : ''
    const id = typeof q.id === 'string' ? q.id.trim() : ''
    const question = typeof q.question === 'string' ? q.question.trim() : ''
    if (!header || !id || !question || options.length === 0) return null
    questions.push({ header, id, question, options })
  }
  return questions
}

function readUserInputAnswersFromItem(item: TurnItemJson): UserInputAnswer[] | undefined {
  const detail = typeof item.detail === 'string' ? item.detail.trim() : ''
  if (!detail) return undefined
  try {
    const parsed = JSON.parse(detail) as unknown
    const rawAnswers =
      parsed && typeof parsed === 'object'
        ? (parsed as Record<string, unknown>).answers
        : undefined
    if (!Array.isArray(rawAnswers)) return undefined
    const answers = rawAnswers
      .map((rawAnswer): UserInputAnswer | null => {
        if (!rawAnswer || typeof rawAnswer !== 'object') return null
        const answer = rawAnswer as Record<string, unknown>
        const id = typeof answer.id === 'string' ? answer.id.trim() : ''
        const label = typeof answer.label === 'string' ? answer.label.trim() : ''
        const value = typeof answer.value === 'string' ? answer.value.trim() : ''
        if (!id || !label) return null
        return { id, label, value }
      })
      .filter((answer): answer is UserInputAnswer => answer != null)
    return answers.length ? answers : undefined
  } catch {
    return undefined
  }
}

function readUserInputQuestionsFromItem(item: TurnItemJson): UserInputQuestion[] | null {
  const detail = typeof item.detail === 'string' ? item.detail.trim() : ''
  if (!detail) return null
  try {
    return readUserInputQuestions(JSON.parse(detail))
  } catch {
    return null
  }
}

function looksLikeUserInputToolItem(item: TurnItemJson): boolean {
  const summary = item.summary.toLowerCase()
  if (summary.includes(REQUEST_USER_INPUT_TOOL)) return true
  return readUserInputAnswersFromItem(item) != null
}

function toolSummaryFromStartedPayload(payload: Record<string, unknown>, fallback: string): string {
  const tool = readPayloadTool(payload)
  if (tool?.name) {
    return tool.name
  }
  const it = readPayloadItem(payload)
  if (it?.summary) return it.summary
  return fallback
}

function readRuntimeError(body: string, fallback: string): RuntimeErrorJson & { message: string } {
  if (!body) return { message: fallback }
  try {
    const parsed = JSON.parse(body) as RuntimeErrorJson & {
      detail?: { message?: string; error?: string }
    }
    const detail =
      parsed.detail && typeof parsed.detail === 'object' ? parsed.detail : undefined
    const detailMessage =
      typeof detail?.message === 'string' && detail.message.trim() ? detail.message.trim() : ''
    const detailError =
      typeof detail?.error === 'string' && detail.error.trim() ? detail.error.trim() : ''
    const nestedError =
      parsed.error && typeof parsed.error === 'object' ? parsed.error.message?.trim() ?? '' : ''
    const topLevelError =
      typeof parsed.error === 'string' && parsed.error.trim() ? parsed.error.trim() : ''
    const message =
      detailMessage ||
      (typeof parsed.message === 'string' && parsed.message.trim()
        ? parsed.message.trim()
        : detailError
          ? detailError
          : topLevelError
            ? topLevelError
            : nestedError
              ? nestedError
              : fallback)
    const errorCode = detailError || topLevelError || undefined
    return {
      ...(errorCode ? { error: errorCode } : {}),
      message
    }
  } catch {
    /* use raw body */
  }
  return { message: body.trim() || fallback }
}

function toRuntimeError(info: RuntimeErrorJson & { message: string }): Error {
  return new Error(
    info.error
      ? JSON.stringify({ error: info.error, message: info.message })
      : info.message
  )
}

function runtimeExecutionFlags(settings: AppSettingsV1): RuntimeExecutionFlags {
  return {
    auto_approve: settings.deepseek.approvalPolicy === 'auto',
    trust_mode: settings.deepseek.sandboxMode === 'danger-full-access'
  }
}

function shouldAutoDenyApprovals(settings: AppSettingsV1): boolean {
  return settings.deepseek.approvalPolicy === 'never'
}

function toolBlockFromItem(item: TurnItemJson): ToolBlock {
  const status = statusFromString(item.status)
  const rawDetail = typeof item.detail === 'string' && item.detail.trim() ? item.detail : undefined
  // Truncate to keep blocks[] bounded: full detail is lazy-loaded via
  // fetchItemDetail when the user expands a tool block.
  const detail = rawDetail
  const detailTruncated = rawDetail != null && rawDetail.length > TOOL_DETAIL_MAX_CHARS
  const meta = (item.metadata ?? undefined) as Record<string, unknown> | undefined
  return {
    kind: 'tool',
    id: item.id,
    createdAt: item.started_at ?? item.ended_at ?? undefined,
    summary: item.summary || item.kind,
    status,
    toolKind: toToolKind(item.kind),
    detail: detailTruncated ? rawDetail!.slice(0, TOOL_DETAIL_MAX_CHARS) : detail,
    detailTruncated: detailTruncated || undefined,
    filePath: deriveFilePath(item),
    meta
  }
}

function itemCreatedAt(item: TurnItemJson): string | undefined {
  return item.started_at ?? item.ended_at ?? undefined
}

function isPhaseBridgeItem(it: TurnItemJson): boolean {
  return it.kind === 'status' && it.metadata?.phase_bridge === true
}

function readPhaseBridgeAfterReasoningId(it: TurnItemJson): string | undefined {
  const id = it.metadata?.after_reasoning_id
  return typeof id === 'string' && id.trim() ? id.trim() : undefined
}

function readAgentSegment(it: TurnItemJson): 'mid_turn_preface' | 'final_answer' | undefined {
  const segment = it.metadata?.agent_segment
  if (segment === 'mid_turn_preface' || segment === 'final_answer') return segment
  return undefined
}

function readProcessIntent(it: TurnItemJson): ProcessIntentMeta | undefined {
  const raw = it.metadata?.process_intent
  if (!raw || typeof raw !== 'object') return undefined
  const meta = raw as Record<string, unknown>
  const scope = meta.scope
  const source = meta.source
  if (scope !== 'pre_tool' && scope !== 'milestone') return undefined
  if (source !== 'primary_model' && source !== 'narration_service' && source !== 'none') {
    return undefined
  }
  return {
    scope,
    source,
    phase: typeof meta.phase === 'string' ? meta.phase : undefined,
    batch: typeof meta.batch === 'string' ? meta.batch : undefined,
    toolCount: typeof meta.tool_count === 'number' ? meta.tool_count : undefined,
    anchors: Array.isArray(meta.anchors)
      ? meta.anchors.filter((a): a is string => typeof a === 'string')
      : undefined
  }
}

/**
 * Read session-level mounted-plugin state from a STATUS item's metadata.
 * Returns:
 *  - `undefined` when the item carries no `active_plugin` signal (normal status)
 *  - `null` when the payload is null (explicit `@plugin:off` unmount)
 *  - the parsed meta when a plugin is mounted
 */
function readActivePlugin(it: TurnItemJson): ActivePluginMeta | null | undefined {
  const meta = it.metadata
  if (!meta || typeof meta !== 'object' || !('active_plugin' in meta)) return undefined
  const raw = (meta as Record<string, unknown>).active_plugin
  if (raw === null || raw === undefined) return null
  if (typeof raw !== 'object') return undefined
  const p = raw as Record<string, unknown>
  const name = p.name
  if (typeof name !== 'string' || !name) return null
  return {
    name,
    version: typeof p.version === 'string' ? p.version : '',
    path: typeof p.path === 'string' ? p.path : '',
    scope: typeof p.scope === 'string' ? p.scope : '',
    trusted: Boolean(p.trusted),
    permissions: Array.isArray(p.permissions)
      ? p.permissions.filter((x): x is string => typeof x === 'string')
      : [],
    mcpActive: Boolean(p.mcp_active)
  }
}

/** Plugin mount/unmount STATUS items drive the composer badge only — not the timeline. */
function isPluginMountStatusItem(it: TurnItemJson): boolean {
  if (readActivePlugin(it) !== undefined) return true
  const text = (it.detail ?? it.summary ?? '').trim()
  return text.startsWith('[plugin]')
}

function isSubagentMailboxItem(it: TurnItemJson): boolean {
  const meta = it.metadata && typeof it.metadata === 'object' ? it.metadata : undefined
  return it.kind === 'status' && meta?.subagent_mailbox === true
}

function isWorkflowProgressItem(it: TurnItemJson): boolean {
  const meta = it.metadata && typeof it.metadata === 'object' ? it.metadata : undefined
  return it.kind === 'status' && meta?.workflow_progress === true
}

/** Plain-text StatusEvent dumps of workflow progress (duplicate of WorkflowBlock). */
function isWorkflowStatusTextItem(it: TurnItemJson): boolean {
  if (it.kind !== 'status') return false
  if (isWorkflowProgressItem(it)) return false
  const text = (it.detail ?? it.summary ?? '').trim()
  return /^(?:Workflow (?:running|completed|failed|cancelled)\b)/i.test(text)
}

function readWorkflowProgressFromItem(it: TurnItemJson): WorkflowProgressPayload | null {
  const detail = typeof it.detail === 'string' ? it.detail.trim() : ''
  if (!detail) return null
  try {
    const parsed = JSON.parse(detail) as Record<string, unknown>
    const toolCallId =
      typeof parsed.tool_call_id === 'string'
        ? parsed.tool_call_id
        : typeof it.metadata === 'object' && it.metadata && typeof it.metadata.tool_call_id === 'string'
          ? String(it.metadata.tool_call_id)
          : ''
    const payload = {
      tool_call_id: toolCallId,
      workflow_name: parsed.workflow_name,
      snapshot: parsed.snapshot,
      completed: parsed.completed === true || it.status === 'completed',
      status: parsed.status,
      run_id: parsed.run_id
    }
    const progress = parseWorkflowProgressPayload(payload)
    if (progress) return progress
    const snapshot = parseWorkflowSnapshot(parsed.snapshot)
    if (!snapshot || !toolCallId) return null
    return {
      toolCallId,
      workflowName:
        typeof parsed.workflow_name === 'string' ? parsed.workflow_name : snapshot.name,
      snapshot,
      completed: parsed.completed === true || it.status === 'completed',
      status:
        parsed.status === 'running' ||
        parsed.status === 'completed' ||
        parsed.status === 'failed' ||
        parsed.status === 'cancelled' ||
        parsed.status === 'timed_out'
          ? parsed.status
          : undefined,
      runId: typeof parsed.run_id === 'string' ? parsed.run_id : undefined
    }
  } catch {
    return null
  }
}

function readSubagentMailboxFromItem(it: TurnItemJson): MailboxMessageJson | null {
  const detail = typeof it.detail === 'string' ? it.detail.trim() : ''
  if (!detail) return null
  try {
    const parsed = JSON.parse(detail) as Record<string, unknown>
    const message = parsed.message
    if (!message || typeof message !== 'object') return null
    const msg = message as Record<string, unknown>
    if (typeof msg.agent_id !== 'string' || !msg.agent_id.trim()) return null
    return {
      kind: typeof msg.kind === 'string' ? msg.kind : '',
      agent_id: msg.agent_id,
      agent_type: typeof msg.agent_type === 'string' ? msg.agent_type : null,
      status: typeof msg.status === 'string' ? msg.status : null,
      tool_name: typeof msg.tool_name === 'string' ? msg.tool_name : null,
      step: typeof msg.step === 'number' ? msg.step : null,
      ok: typeof msg.ok === 'boolean' ? msg.ok : null,
      parent_id: typeof msg.parent_id === 'string' ? msg.parent_id : null,
      summary: typeof msg.summary === 'string' ? msg.summary : null,
      error: typeof msg.error === 'string' ? msg.error : null
    }
  } catch {
    return null
  }
}

function upsertSubagentBlock(
  blocks: ChatBlock[],
  cards: Record<string, SubagentCardState>,
  agentId: string,
  createdAt?: string
): ChatBlock[] {
  const card = cards[agentId]
  if (!card) return blocks
  const nextBlock = subagentBlockFromCard(card, createdAt)
  const idx = blocks.findIndex((b) => b.kind === 'subagent' && b.agentId === agentId)
  if (idx >= 0) {
    const next = [...blocks]
    next[idx] = { ...nextBlock, createdAt: blocks[idx]?.createdAt ?? nextBlock.createdAt }
    return next
  }
  return [...blocks, nextBlock]
}

function userMessageEventFromItem(item: TurnItemJson): UserMessageEventPayload | null {
  if (item.kind !== 'user_message') return null
  const meta =
    item.metadata && typeof item.metadata === 'object'
      ? (item.metadata as Record<string, unknown>)
      : undefined
  const modelLabel = displayModelFromUserMessageMeta(meta)
  const rawText = item.detail ?? item.summary
  const text = unwrapClawUserPromptForDisplay(rawText)
  return {
    itemId: item.id,
    turnId: deriveTurnId(item),
    createdAt: itemCreatedAt(item),
    text,
    ...(modelLabel ? { modelLabel } : {})
  }
}

function createSseStreamId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `sse-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

export class DeepseekRuntimeProvider implements AgentProvider {
  readonly id: AgentProviderId = 'deepseek-runtime'
  readonly displayName = 'DeepSeek TUI'

  getCapabilities(): {
    interrupt: boolean
    stream: boolean
    approvals: boolean
    attachFiles: boolean
  } {
    return { interrupt: true, stream: true, approvals: true, attachFiles: false }
  }

  async connect(options?: { light?: boolean }): Promise<void> {
    const r = await window.dsGui.runtimeRequest('/health', 'GET')
    if (!r.ok) {
      throw toRuntimeError(readRuntimeError(r.body, `runtime unhealthy (${r.status || 'offline'})`))
    }

    if (options?.light) {
      return
    }

    const authProbe = await window.dsGui.runtimeRequest('/v1/threads?limit=1', 'GET')
    if (!authProbe.ok) {
      const info = readRuntimeError(authProbe.body, `failed to list threads (${authProbe.status || 0})`)
      if (authProbe.status === 401 && /bearer token required/i.test(info.message)) {
        throw toRuntimeError({
          error: 'runtime_auth_required',
          message: 'The local runtime requires a bearer token for thread APIs.'
        })
      }
      throw toRuntimeError(info)
    }
  }

  async isThreadTurnActive(threadId: string): Promise<boolean> {
    const r = await window.dsGui.runtimeRequest(
      `/v1/threads/${encodeURIComponent(threadId)}/active`,
      'GET'
    )
    if (!r.ok) {
      throw toRuntimeError(readRuntimeError(r.body, `failed to read thread activity (${r.status || 0})`))
    }
    const body = JSON.parse(r.body) as { active?: boolean }
    return body.active === true
  }

  async warmThread(threadId: string): Promise<void> {
    const r = await window.dsGui.runtimeRequest(
      `/v1/threads/${encodeURIComponent(threadId)}/warmup`,
      'POST'
    )
    if (!r.ok) {
      throw toRuntimeError(readRuntimeError(r.body, `failed to warm thread (${r.status || 0})`))
    }
  }

  async submitApprovalDecision(
    approvalId: string,
    decision: 'allow' | 'deny',
    remember = false
  ): Promise<void> {
    const r = await window.dsGui.runtimeRequest(
      `/v1/approvals/${encodeURIComponent(approvalId)}`,
      'POST',
      JSON.stringify({ decision, remember })
    )
    if (!r.ok) throw toRuntimeError(readRuntimeError(r.body, `approval decision failed: ${r.status}`))
  }

  async submitElevationDecision(
    elevationId: string,
    decision: 'allow' | 'deny'
  ): Promise<void> {
    const r = await window.dsGui.runtimeRequest(
      `/v1/elevations/${encodeURIComponent(elevationId)}`,
      'POST',
      JSON.stringify({ decision })
    )
    if (!r.ok) {
      throw toRuntimeError(readRuntimeError(r.body, `elevation decision failed: ${r.status}`))
    }
  }

  async fetchPendingApprovals(threadId: string): Promise<ApprovalRequestPayload[]> {
    const r = await window.dsGui.runtimeRequest(
      `/v1/approvals/pending?thread_id=${encodeURIComponent(threadId)}`,
      'GET'
    )
    if (!r.ok) return []
    const rows = JSON.parse(r.body) as Array<Record<string, unknown>>
    return rows
      .map((row) => approvalPayloadFromRecord(row))
      .filter((row): row is ApprovalRequestPayload => row !== null)
  }

  async submitEvolutionDecision(
    recordId: string,
    decision: 'approve' | 'reject',
    threadId: string
  ): Promise<void> {
    const action = decision === 'approve' ? 'approve' : 'reject'
    const r = await window.dsGui.runtimeRequest(
      `/v1/evolution/${encodeURIComponent(recordId)}/${action}?thread_id=${encodeURIComponent(threadId)}`,
      'POST',
      decision === 'reject' ? JSON.stringify({ reason: 'user rejected' }) : undefined
    )
    if (!r.ok) {
      throw toRuntimeError(readRuntimeError(r.body, `evolution decision failed: ${r.status}`))
    }
  }

  async fetchPendingEvolution(threadId: string): Promise<EvolutionProposalPayload[]> {
    const r = await window.dsGui.runtimeRequest(
      `/v1/evolution/pending?thread_id=${encodeURIComponent(threadId)}`,
      'GET'
    )
    if (!r.ok) return []
    const rows = JSON.parse(r.body) as Array<Record<string, unknown>>
    return rows
      .map((row) => {
        const nested =
          row.mutation && typeof row.mutation === 'object'
            ? (row.mutation as Record<string, unknown>)
            : {}
        return evolutionPayloadFromRecord({
          record_id: row.id ?? row.record_id,
          kind: nested.kind ?? row.kind,
          summary: row.summary ?? row.reason ?? nested.reason,
          asset_path: row.asset_path
        })
      })
      .filter((row): row is EvolutionProposalPayload => row !== null)
  }

  async fetchPendingUserInputs(threadId: string): Promise<UserInputRequestPayload[]> {
    const r = await window.dsGui.runtimeRequest(
      `/v1/user-inputs/pending?thread_id=${encodeURIComponent(threadId)}`,
      'GET'
    )
    if (!r.ok) return []
    const rows = JSON.parse(r.body) as Array<Record<string, unknown>>
    return rows
      .map((row) => {
        const requestId = String(row.request_id ?? row.id ?? '')
        const rawQuestions = row.questions
        const questions = readUserInputQuestions(rawQuestions)
        if (!requestId || !questions) return null
        return {
          itemId: requestId,
          requestId,
          questions
        }
      })
      .filter((row): row is UserInputRequestPayload => row != null)
  }

  async exportThreadToSession(
    threadId: string,
    sessionId?: string
  ): Promise<{ sessionId: string; path: string; threadId: string }> {
    const query = sessionId
      ? `?session_id=${encodeURIComponent(sessionId)}`
      : ''
    const r = await window.dsGui.runtimeRequest(
      `/v1/threads/${encodeURIComponent(threadId)}/export-session${query}`,
      'POST'
    )
    if (!r.ok) throw toRuntimeError(readRuntimeError(r.body, 'export session failed'))
    const body = JSON.parse(r.body) as Record<string, unknown>
    return {
      sessionId: String(body.session_id ?? ''),
      path: String(body.path ?? ''),
      threadId: String(body.thread_id ?? threadId)
    }
  }

  async listThreads(): Promise<NormalizedThread[]> {
    const r = await window.dsGui.runtimeRequest('/v1/threads?limit=50', 'GET')
    if (!r.ok) throw toRuntimeError(readRuntimeError(r.body, 'failed to list threads'))
    const rows = JSON.parse(r.body) as ThreadRecordJson[]
    return rows
      .filter((t) => t.archived !== true)
      .map((t) => ({
        id: t.id,
        title: titleFromThread(t),
        updatedAt: t.updated_at,
        model: t.model,
        mode: t.mode,
        workspace: t.workspace,
        status: t.status
      }))
  }

  async createThread(input: {
    workspace?: string
    title?: string
    mode?: string
    provider?: string
    model?: string
  }): Promise<NormalizedThread> {
    const settings = await window.dsGui.getSettings()
    const flags = runtimeExecutionFlags(settings)
    const body = JSON.stringify({
      workspace: input.workspace,
      mode: input.mode ?? 'agent',
      provider: input.provider,
      model: input.model,
      ...flags
    })
    const r = await window.dsGui.runtimeRequest('/v1/threads', 'POST', body)
    if (!r.ok) throw toRuntimeError(readRuntimeError(r.body, 'failed to create thread'))
    const t = JSON.parse(r.body) as ThreadRecordJson
    if (input.title) {
      await window.dsGui.runtimeRequest(
        `/v1/threads/${encodeURIComponent(t.id)}`,
        'PATCH',
        JSON.stringify({ title: input.title })
      )
    }
    return {
      id: t.id,
      title: input.title || titleFromThread(t),
      updatedAt: t.updated_at,
      model: t.model,
      mode: t.mode,
      workspace: t.workspace,
      status: t.status
    }
  }

  async getThreadDetail(threadId: string): Promise<{
    blocks: ChatBlock[]
    latestSeq: number
    threadStatus?: string
    latestTurnId?: string
    latestUserMessageId?: string
  }> {
    const r = await window.dsGui.runtimeRequest(`/v1/threads/${encodeURIComponent(threadId)}`, 'GET')
    if (!r.ok) throw toRuntimeError(readRuntimeError(r.body, 'failed to load thread'))
    const detail = JSON.parse(r.body) as ThreadDetailJson
    let blocks: ChatBlock[] = []
    let subagentCards: Record<string, SubagentCardState> = {}
    const latestTurn = Array.isArray(detail.turns) ? detail.turns.at(-1) : undefined
    let latestTurnId: string | undefined = latestTurn?.id
    const latestTurnStatus = latestTurn?.status
    let latestUserMessageId: string | undefined
    const narrationByReasoningId = new Map<string, string>()
    for (const it of detail.items) {
      if (!isPhaseBridgeItem(it)) continue
      const afterId = readPhaseBridgeAfterReasoningId(it)
      const text = it.summary?.trim()
      if (afterId && text) narrationByReasoningId.set(afterId, text)
    }
    // Latest mounted-plugin signal across the whole thread (last wins; items
    // are chronological). null = explicit unmount, undefined = never mounted.
    let activePlugin: ActivePluginMeta | null | undefined = undefined
    for (const it of detail.items) {
      const ap = readActivePlugin(it)
      if (ap !== undefined) activePlugin = ap
      latestTurnId = deriveTurnId(it) ?? latestTurnId
      if (it.kind === 'user_message') {
        latestUserMessageId = it.id
        const meta =
          it.metadata && typeof it.metadata === 'object'
            ? (it.metadata as Record<string, unknown>)
            : undefined
        const modelLabel = displayModelFromUserMessageMeta(meta)
        const rawText = it.detail ?? it.summary
        blocks.push({
          kind: 'user',
          id: it.id,
          createdAt: itemCreatedAt(it),
          text: unwrapClawUserPromptForDisplay(rawText),
          ...(modelLabel ? { modelLabel } : {})
        })
      } else if (it.kind === 'agent_message') {
        // Route purely on persisted metadata: the runtime tags every
        // agent_message with its segment. Untagged legacy items stay in the
        // process trace; nothing is promoted by position or turn status.
        const text = it.detail ?? it.summary
        const agentSegment = readAgentSegment(it)
        const processIntent = readProcessIntent(it)
        if (text.trim() || processIntent) {
          blocks.push({
            kind: 'assistant',
            id: it.id,
            createdAt: itemCreatedAt(it),
            text,
            ...(agentSegment ? { agentSegment } : {}),
            ...(processIntent ? { processIntent } : {})
          })
        }
      } else if (it.kind === 'agent_reasoning') {
        const text = it.detail ?? it.summary
        if (text.trim()) {
          const narration = narrationByReasoningId.get(it.id)
          blocks.push({
            kind: 'reasoning',
            id: it.id,
            createdAt: itemCreatedAt(it),
            text,
            ...(narration ? { narration } : {})
          })
        }
      } else if (it.kind === 'tool_call' && looksLikeUserInputToolItem(it)) {
        const questions = readUserInputQuestionsFromItem(it)
        if (questions) {
          const status =
            statusFromString(it.status) === 'error'
              ? 'error'
              : statusFromString(it.status) === 'running'
                ? 'pending'
                : 'submitted'
          blocks.push({
            kind: 'user_input',
            id: it.id,
            createdAt: itemCreatedAt(it),
            requestId: it.id,
            questions,
            status,
            answers: readUserInputAnswersFromItem(it),
            ...(status === 'error' ? { errorMessage: it.detail ?? it.summary } : {})
          })
        } else {
          blocks.push(toolBlockFromItem(it))
        }
      } else if (TOOL_ITEM_KINDS.has(it.kind)) {
        const toolBlock = toolBlockFromItem(it)
        blocks.push(toolBlock)
        const snap = workflowSnapshotFromToolMeta(toolBlock.meta)
        if (snap) {
          blocks = upsertWorkflowBlock(blocks, {
            toolCallId: it.id,
            workflowName: snap.name,
            snapshot: snap,
            completed: statusFromString(it.status) !== 'running',
            runId: workflowRunIdFromToolMeta(toolBlock.meta)
          })
        }
      } else if (it.kind === 'error') {
        blocks.push({ kind: 'system', id: it.id, createdAt: itemCreatedAt(it), text: `⚠ ${it.detail ?? it.summary}` })
      } else if (isSubagentMailboxItem(it)) {
        const mailbox = readSubagentMailboxFromItem(it)
        if (mailbox) {
          subagentCards = applyMailboxMessage(subagentCards, mailbox)
          blocks = upsertSubagentBlock(blocks, subagentCards, mailbox.agent_id, itemCreatedAt(it))
        }
      } else if (isWorkflowProgressItem(it)) {
        const progress = readWorkflowProgressFromItem(it)
        if (progress) {
          blocks = upsertWorkflowBlock(blocks, progress)
        }
      } else if (it.kind === 'status' || it.kind === 'context_compaction') {
        if (isPhaseBridgeItem(it)) continue
        // Mount/unmount notes are session chrome (footer badge), not chat lines.
        if (it.kind === 'status' && isPluginMountStatusItem(it)) continue
        // Workflow progress text StatusEvents duplicate the WorkflowBlock card.
        if (it.kind === 'status' && isWorkflowStatusTextItem(it)) continue
        const text = it.summary || it.kind
        blocks.push({ kind: 'system', id: it.id, createdAt: itemCreatedAt(it), text })
      }
    }
    return {
      blocks,
      latestSeq: detail.latest_seq ?? 0,
      threadStatus: detail.thread.status ?? latestTurnStatus,
      latestTurnId,
      latestUserMessageId,
      ...(activePlugin !== undefined ? { activePlugin } : {})
    }
  }

  async fetchItemDetail(itemId: string): Promise<{ detail: string | null }> {
    const r = await window.dsGui.runtimeRequest(
      `/v1/items/${encodeURIComponent(itemId)}`,
      'GET'
    )
    if (!r.ok) {
      throw toRuntimeError(readRuntimeError(r.body, `failed to load item ${itemId}`))
    }
    const item = JSON.parse(r.body) as { detail?: string | null }
    return { detail: item.detail ?? null }
  }

  async sendUserMessage(
    threadId: string,
    text: string,
    options?: {
      mode?: string
      provider?: string
      model?: string
      reasoningEffort?: string
      uiSubmitAtMs?: number
      /** Skip persisting a user_message item (plugin mount/unmount control). */
      hidden?: boolean
    }
  ): Promise<{ turnId: string; threadId: string; userMessageItemId?: string }> {
    const settings = await window.dsGui.getSettings()
    const flags = runtimeExecutionFlags(settings)
    const r = await window.dsGui.runtimeRequest(
      `/v1/threads/${encodeURIComponent(threadId)}/turns`,
      'POST',
      JSON.stringify({
        prompt: text,
        mode: options?.mode,
        provider: options?.provider,
        model: options?.model,
        reasoning_effort: options?.reasoningEffort,
        ui_submit_at_ms: options?.uiSubmitAtMs,
        ...(options?.hidden ? { hidden: true } : {}),
        ...flags
      })
    )
    if (!r.ok) throw toRuntimeError(readRuntimeError(r.body, 'failed to start turn'))
    const body = JSON.parse(r.body) as StartTurnResponseJson
    // The runtime returns the newly-allocated turn's `item_ids`; the first
    // element is the user_message item we just created. Caller can persist
    // per-turn metadata (e.g. composer model selection) against this stable id.
    const userItemId =
      Array.isArray(body.turn.item_ids) && typeof body.turn.item_ids[0] === 'string'
        ? body.turn.item_ids[0]
        : undefined
    return { turnId: body.turn.id, threadId: body.thread.id, userMessageItemId: userItemId }
  }

  async steerUserMessage(threadId: string, turnId: string, text: string): Promise<void> {
    const r = await window.dsGui.runtimeRequest(
      `/v1/threads/${encodeURIComponent(threadId)}/turns/${encodeURIComponent(turnId)}/steer`,
      'POST',
      JSON.stringify({ prompt: text })
    )
    if (!r.ok) throw toRuntimeError(readRuntimeError(r.body, 'failed to queue message'))
  }

  async submitUserInputResponse(requestId: string, answers: UserInputAnswer[]): Promise<void> {
    const wireAnswers = answers.map((answer) => ({
      question_id: answer.id,
      value: answer.value.trim() || answer.label.trim()
    }))
    const body = JSON.stringify({ answers: wireAnswers })
    const paths = [
      `/v1/user-inputs/${encodeURIComponent(requestId)}`,
      `/v1/user-input/${encodeURIComponent(requestId)}`
    ]
    let last: RuntimeErrorJson & { message: string } | null = null
    for (const path of paths) {
      const r = await window.dsGui.runtimeRequest(path, 'POST', body)
      if (r.ok) return
      last = readRuntimeError(r.body, `request_user_input response failed: ${r.status}`)
      if (r.status !== 404 && r.status !== 405) break
    }
    throw toRuntimeError(
      last ?? {
        error: 'runtime_request_user_input_unsupported',
        message: 'The runtime does not expose request_user_input responses over HTTP yet.'
      }
    )
  }

  async cancelUserInput(requestId: string): Promise<void> {
    const paths = [
      `/v1/user-inputs/${encodeURIComponent(requestId)}`,
      `/v1/user-input/${encodeURIComponent(requestId)}`
    ]
    let last: RuntimeErrorJson & { message: string } | null = null
    for (const path of paths) {
      const r = await window.dsGui.runtimeRequest(path, 'POST', JSON.stringify({ cancelled: true }))
      if (r.ok) return
      last = readRuntimeError(r.body, `request_user_input cancel failed: ${r.status}`)
      if (r.status !== 404 && r.status !== 405) break
    }
    throw toRuntimeError(
      last ?? {
        error: 'runtime_request_user_input_unsupported',
        message: 'The runtime does not expose request_user_input cancellation over HTTP yet.'
      }
    )
  }

  async interruptTurn(threadId: string, turnId: string): Promise<void> {
    const r = await window.dsGui.runtimeRequest(
      `/v1/threads/${encodeURIComponent(threadId)}/turns/${encodeURIComponent(turnId)}/interrupt`,
      'POST'
    )
    if (!r.ok) throw toRuntimeError(readRuntimeError(r.body, 'failed to interrupt turn'))
  }

  async renameThread(threadId: string, title: string): Promise<void> {
    const r = await window.dsGui.runtimeRequest(
      `/v1/threads/${encodeURIComponent(threadId)}`,
      'PATCH',
      JSON.stringify({ title })
    )
    if (!r.ok) throw toRuntimeError(readRuntimeError(r.body, 'rename thread failed'))
  }

  async deleteThread(threadId: string): Promise<void> {
    // GUI v1 archives threads via PATCH; the runtime never exposed DELETE.
    const r = await window.dsGui.runtimeRequest(
      `/v1/threads/${encodeURIComponent(threadId)}`,
      'PATCH',
      JSON.stringify({ archived: true })
    )
    if (!r.ok) {
      throw toRuntimeError(readRuntimeError(r.body, `archive thread failed: ${r.status}`))
    }
  }

  async forkThread(threadId: string, throughItemId?: string): Promise<NormalizedThread> {
    const body =
      throughItemId != null && throughItemId.trim().length > 0
        ? JSON.stringify({ through_item_id: throughItemId })
        : undefined
    const r = await window.dsGui.runtimeRequest(
      `/v1/threads/${encodeURIComponent(threadId)}/fork`,
      'POST',
      body
    )
    if (!r.ok) throw toRuntimeError(readRuntimeError(r.body, 'fork thread failed'))
    const t = JSON.parse(r.body) as ThreadRecordJson
    return {
      id: t.id,
      title: titleFromThread(t),
      updatedAt: t.updated_at,
      model: t.model,
      mode: t.mode,
      workspace: t.workspace,
      status: t.status
    }
  }

  async rewindThread(threadId: string, beforeItemId: string): Promise<void> {
    const r = await window.dsGui.runtimeRequest(
      `/v1/threads/${encodeURIComponent(threadId)}/rewind`,
      'POST',
      JSON.stringify({ before_item_id: beforeItemId })
    )
    if (!r.ok) throw toRuntimeError(readRuntimeError(r.body, 'rewind thread failed'))
  }

  async resumeThread(threadId: string): Promise<void> {
    const r = await window.dsGui.runtimeRequest(
      `/v1/threads/${encodeURIComponent(threadId)}/resume`,
      'POST'
    )
    if (!r.ok) throw toRuntimeError(readRuntimeError(r.body, 'resume thread failed'))
  }

  async compactThread(threadId: string, reason?: string): Promise<void> {
    const body = reason?.trim() ? JSON.stringify({ reason: reason.trim() }) : '{}'
    const r = await window.dsGui.runtimeRequest(
      `/v1/threads/${encodeURIComponent(threadId)}/compact`,
      'POST',
      body
    )
    if (!r.ok) throw toRuntimeError(readRuntimeError(r.body, 'compact thread failed'))
  }

  async subscribeThreadEvents(
    threadId: string,
    sinceSeq: number,
    sink: ThreadEventSink,
    signal: AbortSignal
  ): Promise<void> {
    const wait = (ms: number): Promise<void> =>
      new Promise((resolve) => {
        if (signal.aborted) {
          resolve()
          return
        }
        const timer = window.setTimeout(() => {
          signal.removeEventListener('abort', onAbort)
          resolve()
        }, ms)
        const onAbort = (): void => {
          window.clearTimeout(timer)
          signal.removeEventListener('abort', onAbort)
          resolve()
        }
        signal.addEventListener('abort', onAbort, { once: true })
      })

    const isFatalSseStatus = (status: number | undefined): boolean =>
      typeof status === 'number' && status >= 400 && status < 500 && status !== 408 && status !== 429

    let nextSinceSeq = sinceSeq
    let reconnectDelayMs = 750
    let consecutiveFailures = 0
    // After ~6 consecutive transient failures (~30 s of backoff) surface the
    // error to the UI instead of silently retrying forever — covers "Python
    // runtime crashed" / "port reclaimed" cases that would otherwise look like
    // a hung GUI.
    const RECONNECT_FAILURE_LIMIT = 6

    while (!signal.aborted) {
      const streamId = createSseStreamId()
      try {
        const outcome = await new Promise<{ type: 'end' } | { type: 'error'; error: Error; status?: number }>(
          async (resolve) => {
            let settled = false
            let deltaFlushFrame = 0
            let pendingDeltas: ThreadDeltaEvent[] = []

            const flushPendingDeltas = (): void => {
              if (deltaFlushFrame) {
                window.cancelAnimationFrame(deltaFlushFrame)
                deltaFlushFrame = 0
              }
              if (pendingDeltas.length === 0) return
              const batch = pendingDeltas
              pendingDeltas = []
              sink.onDeltas(batch)
            }

            const scheduleDeltaFlush = (): void => {
              if (deltaFlushFrame) return
              deltaFlushFrame = window.requestAnimationFrame(() => {
                deltaFlushFrame = 0
                flushPendingDeltas()
              })
            }

            const cleanup = (): void => {
              offData()
              offEnd()
              offErr()
              if (deltaFlushFrame) {
                window.cancelAnimationFrame(deltaFlushFrame)
                deltaFlushFrame = 0
              }
              pendingDeltas = []
              signal.removeEventListener('abort', onAbort)
            }

            const finish = (result: { type: 'end' } | { type: 'error'; error: Error; status?: number }): void => {
              if (settled) return
              settled = true
              flushPendingDeltas()
              cleanup()
              resolve(result)
            }

            const offData = window.dsGui.onSseEvent(({ streamId: sid, data }) => {
              if (sid !== streamId) return
              reconnectDelayMs = 750
              consecutiveFailures = 0
              const row = data as {
                seq?: number
                event?: string
                payload?: Record<string, unknown>
              }
              const eventSeq = typeof row.seq === 'number' ? row.seq : undefined
              if (eventSeq !== undefined) {
                nextSinceSeq = Math.max(nextSinceSeq, eventSeq)
              }
              if (typeof row.seq === 'number') {
                if (row.event !== 'item.delta') {
                  sink.onSeq(row.seq)
                }
              }
              const ev = row.event
              const payload = row.payload ?? {}

              if (ev === 'item.delta') {
                const delta = (payload.delta as string) || ''
                const kind = payload.kind as string | undefined
                if ((kind === 'agent_message' || kind === 'agent_reasoning') && delta) {
                  pendingDeltas.push({ text: delta, kind, seq: eventSeq })
                  scheduleDeltaFlush()
                }
                return
              }

              flushPendingDeltas()

              if (ev === 'item.started') {
                const it = readPayloadItem(payload)
                if (it?.kind === 'user_message') {
                  const userMessage = userMessageEventFromItem(it)
                  if (userMessage) sink.onUserMessage(userMessage)
                  return
                }
                if (it && TOOL_ITEM_KINDS.has(it.kind)) {
                  const tool = readPayloadTool(payload)
                  if (tool?.name === REQUEST_USER_INPUT_TOOL) {
                    const questions = readUserInputQuestions(tool.input)
                    if (questions) {
                      sink.onUserInput({
                        itemId: it.id,
                        requestId: tool.id ?? it.id,
                        questions
                      })
                      return
                    }
                  }
                  const label = toolSummaryFromStartedPayload(payload, it.summary || it.kind)
                  sink.onTool({
                    itemId: it.id,
                    summary: label,
                    status: 'running',
                    toolKind: toToolKind(it.kind),
                    filePath: deriveFilePath(it),
                    meta: metaWithToolInput(
                      it.metadata as Record<string, unknown> | undefined,
                      tool?.input
                    )
                  })
                }
                return
              }

              if (ev === 'item.completed' || ev === 'item.failed') {
                const it = readPayloadItem(payload)
                if (it?.kind === 'user_message') {
                  const userMessage = userMessageEventFromItem(it)
                  if (userMessage) sink.onUserMessage(userMessage)
                  return
                }
                if (
                  it &&
                  isPhaseBridgeItem(it) &&
                  sink.onPhaseNarration
                ) {
                  const afterId = readPhaseBridgeAfterReasoningId(it)
                  const text = it.summary?.trim()
                  if (afterId && text) sink.onPhaseNarration(afterId, text)
                  return
                }
                // Plugin mount/unmount rides on STATUS metadata → composer badge
                // only. Do not also push a system transcript line.
                if (it && it.kind === 'status' && sink.onActivePluginChange) {
                  const ap = readActivePlugin(it)
                  if (ap !== undefined) sink.onActivePluginChange(ap)
                }
                if (it && it.kind === 'status' && isPluginMountStatusItem(it)) {
                  return
                }
                if (it && it.kind === 'status' && isWorkflowStatusTextItem(it)) {
                  return
                }
                if (
                  it &&
                  (it.kind === 'status' || it.kind === 'context_compaction') &&
                  sink.onSystemStatus
                ) {
                  const text = it.detail ?? it.summary ?? it.kind
                  sink.onSystemStatus(text, it.id)
                  return
                }
                if (it?.kind === 'error') {
                  const text = (it.detail ?? it.summary ?? 'error').trim()
                  if (text) {
                    if (sink.onSystemStatus) {
                      sink.onSystemStatus(text, it.id)
                    } else {
                      sink.onError(new Error(text))
                    }
                  }
                  return
                }
                if (
                  it &&
                  it.kind === 'agent_message' &&
                  readAgentSegment(it) === 'final_answer' &&
                  sink.onFinalAnswer
                ) {
                  const text = (it.detail ?? it.summary ?? '').trim()
                  if (text) {
                    sink.onFinalAnswer(it.id, text, itemCreatedAt(it))
                    return
                  }
                }
                if (
                  it &&
                  (it.kind === 'agent_reasoning' || it.kind === 'agent_message') &&
                  sink.onLiveSegmentComplete
                ) {
                  sink.onLiveSegmentComplete(
                    it.kind,
                    it.id,
                    itemCreatedAt(it),
                    (it.detail ?? it.summary ?? '').trim(),
                    readProcessIntent(it)
                  )
                  return
                }
                if (it && TOOL_ITEM_KINDS.has(it.kind)) {
                  if (it.kind === 'tool_call' && looksLikeUserInputToolItem(it)) {
                    sink.onUserInputStatus({
                      itemId: it.id,
                      status:
                        ev === 'item.failed' || statusFromString(it.status) === 'error'
                          ? 'error'
                          : 'submitted',
                      answers: readUserInputAnswersFromItem(it),
                      errorMessage:
                        ev === 'item.failed' || statusFromString(it.status) === 'error'
                          ? it.detail ?? it.summary
                          : undefined
                    })
                    return
                  }
                  const status =
                    ev === 'item.failed' || statusFromString(it.status) === 'error'
                      ? 'error'
                      : 'success'
                  const liveDetail =
                    typeof it.detail === 'string' && it.detail.trim() ? it.detail : undefined
                  const liveTruncated =
                    liveDetail != null && liveDetail.length > TOOL_DETAIL_MAX_CHARS
                  const completedTool = readPayloadTool(payload)
                  sink.onTool({
                    itemId: it.id,
                    summary: it.summary || (status === 'error' ? 'tool failed' : 'tool'),
                    status,
                    toolKind: toToolKind(it.kind),
                    detail: liveTruncated ? liveDetail!.slice(0, TOOL_DETAIL_MAX_CHARS) : liveDetail,
                    detailTruncated: liveTruncated || undefined,
                    filePath: deriveFilePath(it),
                    meta: metaWithToolInput(
                      it.metadata as Record<string, unknown> | undefined,
                      completedTool?.input
                    )
                  })
                }
                return
              }

              if (ev === 'turn.completed') {
                const turn = payload.turn as Record<string, unknown> | undefined
                const turnError =
                  typeof turn?.error === 'string' && turn.error.trim() ? turn.error.trim() : ''
                if (turnError) {
                  const turnId =
                    typeof turn?.id === 'string' && turn.id.trim() ? turn.id.trim() : 'unknown'
                  if (sink.onSystemStatus) {
                    sink.onSystemStatus(turnError, `turn-error-${turnId}`)
                  } else {
                    sink.onError(new Error(turnError))
                  }
                }
                sink.onTurnComplete({
                  threadId:
                    typeof turn?.thread_id === 'string'
                      ? turn.thread_id
                      : typeof payload.thread_id === 'string'
                        ? payload.thread_id
                        : undefined,
                  usage:
                    turn?.usage && typeof turn.usage === 'object'
                      ? (turn.usage as Record<string, unknown>)
                      : null
                })
                return
              }


              if (ev === 'thread.updated' && sink.onThreadUpdated) {
                const thread = payload.thread as Record<string, unknown> | undefined
                const changes = (payload.changes as Record<string, unknown> | undefined) ?? {}
                const threadId = typeof thread?.id === 'string' ? thread.id : undefined
                if (threadId) {
                  const titleRaw = thread?.title
                  const title =
                    typeof titleRaw === 'string'
                      ? titleRaw
                      : titleRaw === null
                        ? null
                        : undefined
                  const archived = typeof thread?.archived === 'boolean' ? thread.archived : undefined
                  sink.onThreadUpdated({ threadId, title, archived, changes })
                }
                return
              }

              if (ev === 'user_input.required') {
                const requestId = String(payload.request_id ?? payload.id ?? '')
                const questions = readUserInputQuestions(payload.questions)
                if (requestId && questions && sink.onUserInput) {
                  sink.onUserInput({
                    itemId: requestId,
                    requestId,
                    questions
                  })
                }
                return
              }

              if (ev === 'workflow.progress' && sink.onWorkflowProgress) {
                const progress = parseWorkflowProgressPayload(payload)
                if (progress) {
                  sink.onWorkflowProgress(progress)
                }
                return
              }

              if (ev === 'subagent.mailbox' && sink.onSubagentMailbox) {
                const seq = typeof payload.seq === 'number' ? payload.seq : 0
                const message = payload.message as Record<string, unknown> | undefined
                if (message && typeof message.agent_id === 'string') {
                  sink.onSubagentMailbox({
                    seq,
                    message: message as SubagentMailboxPayload['message']
                  })
                }
                return
              }

              if (ev === 'approval.required') {
                const approvalId = String(payload.approval_id ?? payload.id ?? '')
                if (!approvalId) return
                void window.dsGui
                  .getSettings()
                  .then(async (settings) => {
                    if (runtimeExecutionFlags(settings).auto_approve) {
                      await this.submitApprovalDecision(approvalId, 'allow').catch(() => {
                        /* Runtime may already have auto-approved this request. */
                      })
                      return
                    }
                    if (shouldAutoDenyApprovals(settings)) {
                      await this.submitApprovalDecision(approvalId, 'deny').catch(() => {
                        /* Ignore stale approval ids. */
                      })
                      return
                    }
                    emitApprovalFromSsePayload(sink, payload, approvalId)
                  })
                  .catch(() => {
                    emitApprovalFromSsePayload(sink, payload, approvalId)
                  })
              }

              if (ev === 'elevation.required') {
                const elevationId = String(
                  payload.elevation_id ?? payload.tool_call_id ?? payload.id ?? ''
                )
                if (!elevationId) return
                emitElevationFromSsePayload(sink, payload, elevationId)
              }

              if (ev === 'evolution.suggested') {
                const recordId = String(payload.record_id ?? payload.id ?? '')
                if (!recordId) return
                emitEvolutionFromSsePayload(sink, payload, recordId)
              }
            })

            const offErr = window.dsGui.onSseError(({ streamId: sid, message, status }) => {
              if (sid !== streamId) return
              // 401 means the cached / settings token no longer matches what
              // the runtime expects (e.g. user clicked Regenerate on another
              // window, or CLI rotated the file). Surface a typed error so
              // the UI can show a "Regenerate token" affordance instead of a
              // generic transport message — and never retry, the bearer
              // won't fix itself by waiting.
              const isAuthRejected = status === 401
              const errMessage = isAuthRejected
                ? `runtime_auth_required: ${message ?? 'bearer token rejected by /v1/* — open Settings → Regenerate'}`
                : message ?? `sse error ${status ?? ''}`
              finish({
                type: 'error',
                error: new Error(errMessage),
                status
              })
            })

            const offEnd = window.dsGui.onSseEnd(({ streamId: sid }) => {
              if (sid !== streamId) return
              finish({ type: 'end' })
            })

            const onAbort = (): void => {
              cleanup()
              void window.dsGui.stopSse(streamId)
              resolve({ type: 'end' })
            }

            if (signal.aborted) {
              onAbort()
              return
            }
            signal.addEventListener('abort', onAbort, { once: true })
            try {
              await window.dsGui.startSse(threadId, nextSinceSeq, streamId)
            } catch (e) {
              finish({
                type: 'error',
                error: e instanceof Error ? e : new Error(String(e))
              })
            }
          }
        )

        if (signal.aborted) return
        if (outcome.type === 'error') {
          if (isFatalSseStatus(outcome.status)) {
            sink.onError(outcome.error)
            return
          }
          consecutiveFailures += 1
          if (consecutiveFailures >= RECONNECT_FAILURE_LIMIT) {
            sink.onError(outcome.error)
            return
          }
        } else {
          consecutiveFailures = 0
        }
      } catch (e) {
        if (signal.aborted) return
        if (e instanceof Error && /aborted/i.test(e.message)) return
      } finally {
        void window.dsGui.stopSse(streamId)
      }

      await wait(reconnectDelayMs)
      reconnectDelayMs = Math.min(reconnectDelayMs * 2, 5_000)
    }
  }
}
