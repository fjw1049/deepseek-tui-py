export type AgentProviderId = 'deepseek-runtime'

export type ToolItemKind = 'tool_call' | 'command_execution' | 'file_change'

export type UserInputOption = {
  label: string
  description: string
  /** Optional machine value (e.g. enter_plan_mode / exit_plan_mode outcomes). */
  value?: string
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

export type GoalSnapshotJson = {
  goal_id?: string
  objective: string
  completion_criterion?: string | null
  status: 'active' | 'paused' | 'blocked' | 'complete'
  turns_used?: number
  tokens_used?: number
  wall_clock_ms?: number
  terminal_reason?: string | null
  budget_limits?: {
    token_budget?: number | null
    turn_budget?: number | null
    wall_clock_budget_ms?: number | null
  }
}

export type NormalizedThread = {
  id: string
  title: string
  updatedAt: string
  /** Thread creation time from the runtime (ISO). Used for project sidebar sort. */
  createdAt?: string
  model: string
  mode: string
  workspace?: string
  status?: string
  archived?: boolean
  goal?: GoalSnapshotJson | null
}

export type RuntimeConnectionStatus = 'idle' | 'checking' | 'ready' | 'offline'

/** Result of POST /v1/threads/{id}/restore-code (files restored, conversation kept). */
export type RestoreCodeResult = {
  restoredFiles: string[]
  skippedFiles: string[]
}

/** Result of GET /v1/threads/{id}/rewind-preview — files a rewind-with-restore would touch. */
export type RewindPreview = {
  files: string[]
  skipped: string[]
  /** Paths changed by a third party since the turn — restore leaves them untouched unless forced. */
  conflicts: string[]
  isGit: boolean
  turns: number
}

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
      /** Present when a detached durable task bridged the approval here. */
      taskId?: string
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
      /** Present when a detached durable task bridged the prompt here. */
      taskId?: string
    }
  | {
      kind: 'subagent'
      id: string
      createdAt?: string
      cardKind: 'delegate' | 'fanout'
      agentId: string
      agentType: string
      status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
      /** Spawn assignment preview for dock / list titles. */
      prompt?: string
      summary?: string
      actions?: string[]
      truncated?: boolean
      workers?: { id: string; status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled' }[]
      /** Full step history for StepFlow (delegate cards). */
      steps?: SubagentStepBlock[]
      /** Fanout: per-worker step history. */
      workerSteps?: Record<string, SubagentStepBlock[]>
      parentId?: string | null
      childIds?: string[]
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
  /** Present when a detached durable task bridged the approval here. */
  taskId?: string
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
  taskId?: string
}

export type UserInputStatusPayload = {
  itemId: string
  status: 'submitted' | 'cancelled' | 'error'
  answers?: UserInputAnswer[]
  errorMessage?: string
}

export type SubagentStepBlock = {
  id: string
  kind: 'started' | 'progress' | 'tool' | 'completed' | 'failed' | 'cancelled'
  step?: number | null
  toolName?: string | null
  ok?: boolean | null
  label: string
  input?: string | null
  output?: string | null
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
    /** Provider tool-call id — disambiguates parallel same-name calls in one round. */
    tool_call_id?: string | null
    ok?: boolean | null
    parent_id?: string | null
    summary?: string | null
    error?: string | null
    input_summary?: string | null
    output_summary?: string | null
    /** Spawn assignment preview for dock / list titles. */
    prompt?: string | null
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

/** Live / final turn-level file mutation snapshot (`turn.diff.updated`). */
export type TurnDiffUpdatedPayload = {
  turnId: string
  revision: number
  files: Array<{
    path: string
    op?: string
    additions: number
    deletions: number
    unified_diff: string
    detail_truncated?: boolean
  }>
  totals: { files: number; additions: number; deletions: number }
  mergedUnifiedDiff?: string
  complete: boolean
}

export type ThreadUpdatedPayload = {
  threadId: string
  title?: string | null
  archived?: boolean
  /** Interaction mode after enter/exit plan (or other mode switches). */
  mode?: string
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
  /** Optional: cumulative file mutations for the active turn. */
  onTurnDiffUpdated?(ev: TurnDiffUpdatedPayload): void
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
  /**
   * Optional: session-level mounted-plugin state changed. `null` means
   * explicitly unmounted; the callback is also called on thread load with
   * the latest persisted state. Drives the composer's persistent mount chip.
   */
  onActivePluginChange?(plugin: ActivePluginMeta | null): void
  onGoalUpdated?(goal: GoalSnapshotJson | null): void
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
  listThreads(options?: { includeArchived?: boolean }): Promise<NormalizedThread[]>
  createThread(input: { workspace?: string; title?: string; mode?: string; provider?: string; model?: string }): Promise<NormalizedThread>
  getThreadDetail(threadId: string): Promise<{
    blocks: ChatBlock[]
    latestSeq: number
    threadStatus?: string
    latestTurnId?: string
    latestUserMessageId?: string
    /** Latest mounted-plugin state derived from persisted items. */
    activePlugin?: ActivePluginMeta | null
    goal?: GoalSnapshotJson | null
  }>
  /** Runtime HTTP: GET /v1/items/{id} — lazy-load full tool detail after truncation. */
  fetchItemDetail?(itemId: string): Promise<{ detail: string | null }>
  sendUserMessage(
    threadId: string,
    text: string,
    options?: {
      mode?: string
      provider?: string
      model?: string
      reasoningEffort?: string
      uiSubmitAtMs?: number
      hidden?: boolean
      /** Per-turn override; when omitted, uses global approval dial. */
      autoApprove?: boolean
      trustMode?: boolean
    }
  ): Promise<{ turnId: string; threadId: string; userMessageItemId?: string }>
  steerUserMessage?(threadId: string, turnId: string, text: string): Promise<void>
  interruptTurn(threadId: string, turnId: string): Promise<void>
  renameThread(threadId: string, title: string): Promise<void>
  /** Soft-archive a thread (PATCH archived=true). */
  archiveThread?(threadId: string): Promise<void>
  setThreadArchived?(threadId: string, archived: boolean): Promise<void>
  /** Permanently delete a thread (DELETE). */
  deleteThread(threadId: string): Promise<void>
  purgeThread?(threadId: string): Promise<void>
  /** Permanently delete every soft-archived thread. */
  purgeArchivedThreads?(): Promise<{ deleted: number; requested: number }>
  forkThread?(threadId: string, throughItemId?: string): Promise<NormalizedThread>
  /** Truncate a thread in place: drop `beforeItemId` and everything after it. */
  rewindThread?(
    threadId: string,
    beforeItemId: string,
    restoreFiles?: boolean,
    forceConflicts?: boolean
  ): Promise<void>
  /**
   * Restore workspace files to the state before `beforeItemId`'s turn WITHOUT
   * truncating the conversation (POST /v1/threads/{id}/restore-code).
   */
  restoreCode?(
    threadId: string,
    beforeItemId: string,
    forceConflicts?: boolean
  ): Promise<RestoreCodeResult>
  /**
   * Preview which files a rewind-with-restore (or restore-code) at
   * `beforeItemId` would touch (GET /v1/threads/{id}/rewind-preview).
   */
  rewindPreview?(threadId: string, beforeItemId: string): Promise<RewindPreview>
  resumeThread?(threadId: string): Promise<void>
  /** Runtime HTTP: POST /v1/tasks/{id}/resume */
  resumeTask?(taskId: string): Promise<void>
  /** Runtime HTTP: POST /v1/threads/{id}/agents/{agentId}/resume */
  resumeThreadAgent?(threadId: string, agentId: string): Promise<void>
  compactThread?(threadId: string, reason?: string): Promise<void>
  applyGoalCommand?(
    threadId: string,
    args: string,
    options?: {
      provider?: string
      model?: string
      reasoningEffort?: string
    }
  ): Promise<{
    goal: GoalSnapshotJson | null
    startedTurn: boolean
    statusText: string
    latestTurnId?: string | null
  }>
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
