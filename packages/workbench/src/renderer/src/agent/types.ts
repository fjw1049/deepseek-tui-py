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
  /** Resolved file path for file_change items, when known */
  filePath?: string
  /** Optional structured metadata, e.g. { exit_code, duration_ms, command } */
  meta?: Record<string, unknown>
}

export type ChatBlock =
  | { kind: 'user'; id: string; createdAt?: string; text: string; modelLabel?: string }
  | { kind: 'assistant'; id: string; createdAt?: string; text: string }
  | { kind: 'reasoning'; id: string; createdAt?: string; text: string }
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

export type ThreadUpdatedPayload = {
  threadId: string
  title?: string | null
  archived?: boolean
  /** Subset of fields that actually changed in this update. */
  changes: Record<string, unknown>
}

export type GoalStatusPayload = {
  goal: {
    goal_id: string
    objective: string
    status: 'active' | 'paused' | 'budget_limited' | 'complete'
    tokens_used: number
    token_budget: number | null
    active_seconds: number
  } | null
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
  onTurnComplete(): void
  /** Reasoning or assistant live segment finalized on the runtime. */
  onLiveSegmentComplete?(kind: 'agent_reasoning' | 'agent_message'): void
  onError(err: Error): void
  /** Optional: thread metadata changed (title / archived). */
  onThreadUpdated?(ev: ThreadUpdatedPayload): void
  /** Optional: runtime status line (sub-agent wait, compaction, etc.). */
  onSystemStatus?(text: string, itemId: string): void
  /** Optional: delegate / fanout sub-agent progress cards. */
  onSubagentMailbox?(ev: SubagentMailboxPayload): void
  /** Optional: workflow orchestration progress (upsert by toolCallId). */
  onWorkflowProgress?(ev: WorkflowProgressPayload): void
  /** Optional: goal lifecycle status updates for the process tracker UI. */
  onGoalStatus?(ev: GoalStatusPayload): void
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
  createThread(input: { workspace?: string; title?: string; mode?: string }): Promise<NormalizedThread>
  getThreadDetail(threadId: string): Promise<{
    blocks: ChatBlock[]
    latestSeq: number
    threadStatus?: string
    latestTurnId?: string
    latestUserMessageId?: string
  }>
  sendUserMessage(
    threadId: string,
    text: string,
    options?: { mode?: string; model?: string; uiSubmitAtMs?: number }
  ): Promise<{ turnId: string; threadId: string; userMessageItemId?: string }>
  steerUserMessage?(threadId: string, turnId: string, text: string): Promise<void>
  interruptTurn(threadId: string, turnId: string): Promise<void>
  renameThread(threadId: string, title: string): Promise<void>
  deleteThread(threadId: string): Promise<void>
  forkThread?(threadId: string): Promise<NormalizedThread>
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
  /** Runtime HTTP: POST /v1/threads/import-session */
  importTuiSession?(input: {
    sessionId?: string
    path?: string
    title?: string
    workspace?: string
  }): Promise<NormalizedThread>
  /** Runtime HTTP: GET /v1/sessions */
  listSessions?(limit?: number): Promise<{
    dir: string
    sessions: Array<{
      kind: 'tui' | 'thread'
      sessionId?: string
      path?: string
      threadId?: string
      title: string
      model?: string
      workspace?: string
      messageCount?: number
      modifiedAt: string
      importState: 'available' | 'linked' | 'native'
      linkedThreadId?: string | null
    }>
  }>
  /** Runtime HTTP: POST /v1/threads/{id}/export-session */
  exportThreadToSession?(
    threadId: string,
    sessionId?: string
  ): Promise<{ sessionId: string; path: string; threadId: string }>
  /** Runtime HTTP compatibility path for request_user_input responses. */
  submitUserInputResponse?(requestId: string, answers: UserInputAnswer[]): Promise<void>
  cancelUserInput?(requestId: string): Promise<void>
}
