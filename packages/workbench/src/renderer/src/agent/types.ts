import type { WorkflowSnapshotPayload } from '../lib/workflow-snapshot'

export type AgentProviderId = 'deepseek-runtime'

export type ToolItemKind = 'tool_call' | 'command_execution' | 'file_change'

export type UserInputOption = {
  label: string
  description: string
}

export type UserInputQuestion = {
  header: string
  id: string
  question: string
  options: UserInputOption[]
}

export type UserInputAnswer = {
  id: string
  label: string
  value: string
}

export type NormalizedThread = {
  id: string
  title: string
  updatedAt: string
  model: string
  mode: string
  workspace?: string
  status?: string
  archived?: boolean
}

export type RuntimeConnectionStatus = 'idle' | 'checking' | 'ready' | 'offline'

export type ToolBlock = {
  kind: 'tool'
  id: string
  createdAt?: string
  summary: string
  status: 'running' | 'success' | 'error'
  toolKind?: ToolItemKind
  /** Full text content from runtime: stdout/stderr or unified patch text */
  detail?: string
  /** True when detail was truncated to keep blocks[] bounded; full text via fetchItemDetail */
  detailTruncated?: boolean
  /** Resolved file path for file_change items, when known */
  filePath?: string
  /** Optional structured metadata, e.g. { exit_code, duration_ms, command } */
  meta?: Record<string, unknown>
}

/**
 * Structured narration frame persisted by the runtime alongside a mid-turn
 * preface. Semantics come from these fields, never from parsing display text.
 * `source: 'none'` means no wording exists yet: render a neutral progress
 * state from `phase` / `toolCount` / `anchors`.
 */
export type ProcessIntentMeta = {
  scope: 'pre_tool' | 'milestone'
  source: 'primary_model' | 'narration_service' | 'none'
  phase?: string
  batch?: string
  toolCount?: number
  anchors?: string[]
}

/**
 * Session-level mounted-plugin state. Mirrors the runtime's
 * `metadata.active_plugin` (a `null` payload means explicitly unmounted).
 * Not a per-message property - lives on the chat store and drives the
 * composer's persistent mount chip. `permissions` are the manifest's
 * declared permission strings (e.g. `['read']`).
 */
export type ActivePluginMeta = {
  name: string
  version: string
  path: string
  scope: string
  trusted: boolean
  permissions: string[]
  mcpActive: boolean
}

export type ChatBlock =
  | { kind: 'user'; id: string; createdAt?: string; text: string; modelLabel?: string }
  | {
      kind: 'assistant'
      id: string
      createdAt?: string
      text: string
      agentSegment?: 'mid_turn_preface' | 'final_answer'
      processIntent?: ProcessIntentMeta
    }
  | { kind: 'reasoning'; id: string; createdAt?: string; text: string; narration?: string }
  | ToolBlock
  | { kind: 'system'; id: string; createdAt?: string; text: string }
  | {
      kind: 'approval'
      id: string
      createdAt?: string
      approvalId: string
      summary: string
      inputSummary?: string
      impacts?: string[]
      riskLevel?: string
      presentationRisk?: string
      toolName?: string
      status: 'pending' | 'allowed' | 'denied' | 'error'
      errorMessage?: string
    }
  | {
      kind: 'elevation'
      id: string
      createdAt?: string
      elevationId: string
      toolName?: string
      reason: string
      elevationKind: string
      commandPreview?: string
      status: 'pending' | 'allowed' | 'denied' | 'error'
      errorMessage?: string
    }
  | {
      kind: 'user_input'
      id: string
      createdAt?: string
      requestId: string
      questions: UserInputQuestion[]
      status: 'pending' | 'submitted' | 'cancelled' | 'error'
      answers?: UserInputAnswer[]
      errorMessage?: string
    }
  | {
      kind: 'subagent'
      id: string
      createdAt?: string
      cardKind: 'delegate' | 'fanout'
      agentId: string
      agentType: string
      status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
      summary?: string
      actions?: string[]
      truncated?: boolean
      workers?: { id: string; status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' }[]
    }

  | {
      kind: 'evolution'
      id: string
      createdAt?: string
      recordId: string
      kindLabel: string
      summary: string
      assetPath?: string
      status: 'pending' | 'approved' | 'rejected' | 'error'
      errorMessage?: string
    }
  | {
      kind: 'workflow'
      id: string
      toolCallId: string
      createdAt?: string
      workflowName: string
      status: 'running' | 'completed' | 'failed' | 'cancelled'
      snapshot: WorkflowSnapshotPayload
    }

export type WorkflowProgressPayload = {
  toolCallId: string
  workflowName: string
  snapshot: WorkflowSnapshotPayload
  completed: boolean
  status?: 'running' | 'completed' | 'failed' | 'cancelled' | 'timed_out'
}

export type EvolutionProposalPayload = {
  recordId: string
  kind: string
  summary: string
  assetPath?: string
}

export type ApprovalRequestPayload = {
  approvalId: string
  summary: string
  inputSummary?: string
  impacts?: string[]
  riskLevel?: string
  presentationRisk?: string
  toolName?: string
}

export type ElevationRequestPayload = {
  elevationId: string
  toolName?: string
  reason: string
  elevationKind: string
  commandPreview?: string
}

export type ToolEventPayload = {
  itemId: string
  summary: string
  status: 'running' | 'success' | 'error'
  toolKind?: ToolItemKind
  detail?: string
  detailTruncated?: boolean
  filePath?: string
  meta?: Record<string, unknown>
}

export type UserInputRequestPayload = {
  itemId: string
  requestId: string
  questions: UserInputQuestion[]
}

export type UserInputStatusPayload = {
  itemId: string
  status: 'submitted' | 'cancelled' | 'error'
  answers?: UserInputAnswer[]
  errorMessage?: string
}

export type SubagentMailboxPayload = {
  seq: number
  message: {
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
}

export type UserMessageEventPayload = {
  itemId: string
  turnId?: string
  createdAt?: string
  text: string
  modelLabel?: string
}

export type ThreadDeltaEvent = {
  text: string
  kind: 'agent_message' | 'agent_reasoning'
  seq?: number
}

export type TurnCompletePayload = {
  threadId?: string | null
  usage?: Record<string, unknown> | null
}

export type ThreadUpdatedPayload = {
  threadId: string
  title?: string | null
  archived?: boolean
  /** Subset of fields that actually changed in this update. */
  changes: Record<string, unknown>
}

export type ThreadEventSink = {
  onSeq(seq: number): void
  onDeltas(deltas: ThreadDeltaEvent[]): void
  onUserMessage(ev: UserMessageEventPayload): void
  onTool(ev: ToolEventPayload): void
  onApproval(req: ApprovalRequestPayload): void
  onEvolutionProposal?(req: EvolutionProposalPayload): void
  onElevation?(req: ElevationRequestPayload): void
  onUserInput(req: UserInputRequestPayload): void
  onUserInputStatus(ev: UserInputStatusPayload): void
  onTurnComplete(payload?: TurnCompletePayload): void
  /** Reasoning or assistant live segment finalized on the runtime. */
  onLiveSegmentComplete?(
    kind: 'agent_reasoning' | 'agent_message',
    itemId: string,
    createdAt?: string,
    text?: string,
    processIntent?: ProcessIntentMeta
  ): void
  /** Terminal final answer persisted on the runtime. */
  onFinalAnswer?(itemId: string, text: string, createdAt?: string): void
  /** Phase-bridge narration attached to a completed reasoning segment. */
  onPhaseNarration?(reasoningItemId: string, text: string): void
  onError(err: Error): void
  /** Optional: thread metadata changed (title / archived). */
  onThreadUpdated?(ev: ThreadUpdatedPayload): void
  /** Optional: runtime status line (sub-agent wait, compaction, etc.). */
  onSystemStatus?(text: string, itemId: string): void
  /** Optional: delegate / fanout sub-agent progress cards. */
  onSubagentMailbox?(ev: SubagentMailboxPayload): void
  /** Optional: workflow orchestration progress (upsert by toolCallId). */
  onWorkflowProgress?(ev: WorkflowProgressPayload): void
  /**
   * Optional: session-level mounted-plugin state changed. `null` means
   * explicitly unmounted; the callback is also called on thread load with
   * the latest persisted state. Drives the composer's persistent mount chip.
   */
  onActivePluginChange?(plugin: ActivePluginMeta | null): void
}

export interface AgentProvider {
  readonly id: AgentProviderId
  readonly displayName: string
  getCapabilities(): {
    interrupt: boolean
    stream: boolean
    approvals: boolean
    attachFiles: boolean
  }
  connect(options?: { light?: boolean }): Promise<void>
  isThreadTurnActive?(threadId: string): Promise<boolean>
  warmThread?(threadId: string): Promise<void>
  listThreads(): Promise<NormalizedThread[]>
  createThread(input: { workspace?: string; title?: string; mode?: string; provider?: string; model?: string }): Promise<NormalizedThread>
  getThreadDetail(threadId: string): Promise<{
    blocks: ChatBlock[]
    latestSeq: number
    threadStatus?: string
    latestTurnId?: string
    latestUserMessageId?: string
    /** Latest mounted-plugin state derived from persisted items. */
    activePlugin?: ActivePluginMeta | null
  }>
  /** Runtime HTTP: GET /v1/items/{id} — lazy-load full tool detail after truncation. */
  fetchItemDetail?(itemId: string): Promise<{ detail: string | null }>
  sendUserMessage(
    threadId: string,
    text: string,
    options?: { mode?: string; provider?: string; model?: string; uiSubmitAtMs?: number }
  ): Promise<{ turnId: string; threadId: string; userMessageItemId?: string }>
  steerUserMessage?(threadId: string, turnId: string, text: string): Promise<void>
  interruptTurn(threadId: string, turnId: string): Promise<void>
  renameThread(threadId: string, title: string): Promise<void>
  deleteThread(threadId: string): Promise<void>
  forkThread?(threadId: string, throughItemId?: string): Promise<NormalizedThread>
  /** Truncate a thread in place: drop `beforeItemId` and everything after it. */
  rewindThread?(threadId: string, beforeItemId: string): Promise<void>
  resumeThread?(threadId: string): Promise<void>
  compactThread?(threadId: string, reason?: string): Promise<void>
  subscribeThreadEvents(
    threadId: string,
    sinceSeq: number,
    sink: ThreadEventSink,
    signal: AbortSignal
  ): Promise<void>
  /** Runtime HTTP: POST /v1/approvals/{id} */
  submitApprovalDecision?(
    approvalId: string,
    decision: 'allow' | 'deny',
    remember?: boolean
  ): Promise<void>
  /** Runtime HTTP: POST /v1/elevations/{id} */
  submitElevationDecision?(
    elevationId: string,
    decision: 'allow' | 'deny'
  ): Promise<void>
  /** Runtime HTTP: GET /v1/approvals/pending */
  fetchPendingApprovals?(threadId: string): Promise<ApprovalRequestPayload[]>
  /** Runtime HTTP: POST /v1/evolution/{id}/approve */
  submitEvolutionDecision?(
    recordId: string,
    decision: 'approve' | 'reject',
    threadId: string
  ): Promise<void>
  /** Runtime HTTP: GET /v1/evolution/pending */
  fetchPendingEvolution?(threadId: string): Promise<EvolutionProposalPayload[]>
  /** Runtime HTTP: GET /v1/user-inputs/pending */
  fetchPendingUserInputs?(threadId: string): Promise<UserInputRequestPayload[]>
  /** Runtime HTTP: POST /v1/threads/{id}/export-session */
  exportThreadToSession?(
    threadId: string,
    sessionId?: string
  ): Promise<{ sessionId: string; path: string; threadId: string }>
  /** Runtime HTTP compatibility path for request_user_input responses. */
  submitUserInputResponse?(requestId: string, answers: UserInputAnswer[]): Promise<void>
  cancelUserInput?(requestId: string): Promise<void>
}
