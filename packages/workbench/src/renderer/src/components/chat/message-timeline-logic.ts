/**
 * Pure helpers for MessageTimeline.
 *
 * Kept out of MessageTimeline.tsx so that file only exports React components —
 * mixed component/non-component exports disable Vite Fast Refresh and remount
 * the chat shell (greeting flash) on every HMR touch of the dependency graph.
 */
import type { ChatBlock } from '../../agent/types'
import { isTodoToolBlock } from '../../lib/extract-todos-from-blocks'
import { sanitizeReasoningPlaceholders } from '../../lib/reasoning-text'
import { isMergeableProbeTool } from '../../lib/step-flow-collapse'
import type { StepFlowItem } from './StepFlow'

const THINK_TAG_RE = /<think(?:ing)?>([\s\S]*?)(?:<\/(?:think(?:ing)?|redacted_thinking)>|$)/i

export function splitThink(text: string): { think: string; content: string } {
  const tagged = text.match(THINK_TAG_RE)
  if (!tagged) return { think: '', content: sanitizeReasoningPlaceholders(text) }
  return {
    think: sanitizeReasoningPlaceholders(tagged[1]),
    content: sanitizeReasoningPlaceholders(text.replace(THINK_TAG_RE, ''))
  }
}

// `agent` / `agent_resume` are the current tool names; the agent_* entries are
// legacy fallbacks for replayed history transcripts.
const SUBAGENT_ORCHESTRATION_TOOL_RE =
  /^(?:agent|agent_resume|agent_spawn|spawn_agent|delegate_to_agent|agent_wait|wait|agent_result|agent_list|agent_cancel|agent_send_input)$/i

export type ToolProcessBlock = Extract<ChatBlock, { kind: 'tool' }>

export function toolNameFromProcessBlock(block: ToolProcessBlock): string {
  const metaName = typeof block.meta?.tool_name === 'string' ? block.meta.tool_name : undefined
  if (metaName) return metaName
  const summary = block.summary.trim()
  return summary.split(/[:(]/, 1)[0]?.trim() ?? ''
}

export function isSubagentOrchestrationToolName(name: string | undefined): boolean {
  return !!name && SUBAGENT_ORCHESTRATION_TOOL_RE.test(name.trim())
}

const WORKFLOW_TOOL_RE = /^(?:workflow|workflow_list)$/i

export function isWorkflowToolName(name: string | undefined): boolean {
  return !!name && WORKFLOW_TOOL_RE.test(name.trim())
}

export function turnHasWorkflowBlock(blocks: ChatBlock[]): boolean {
  return blocks.some((block) => block.kind === 'workflow')
}

/** Live runs belong in ProcessTray — keep terminal cards on the timeline. */
export function shouldHideRunningWorkflowBlock(block: ChatBlock): boolean {
  return block.kind === 'workflow' && block.status === 'running'
}

/**
 * When a workflow owns the turn, subagent cards fold into the DAG / dock.
 * Agent-mode turns (no workflow block) keep the SubagentSummaryPanel.
 */
export function shouldFoldSubagentsIntoWorkflow(blocks: ChatBlock[]): boolean {
  return turnHasWorkflowBlock(blocks)
}

/**
 * Hide the raw workflow tool card once a WorkflowBlock exists for the same
 * toolCallId. Keep error cards so failed specs (e.g. invalid fanout) remain
 * visible as the reason for a retry.
 */
export function shouldHideWorkflowToolBlock(
  block: ChatBlock,
  blocks: ChatBlock[]
): boolean {
  if (block.kind !== 'tool' || block.status === 'error') return false
  if (!isWorkflowToolName(toolNameFromProcessBlock(block))) return false
  return blocks.some(
    (candidate) => candidate.kind === 'workflow' && candidate.toolCallId === block.id
  )
}

/** Status bubbles that dump render_workflow_text — duplicate of WorkflowBlock. */
export function isWorkflowStatusSystemText(text: string | undefined): boolean {
  const trimmed = text?.trim() ?? ''
  return /^(?:Workflow (?:running|completed|failed|cancelled)\b)/i.test(trimmed)
}

/**
 * Sub-agent wait/resume StatusEvents — internal handoff, not chat content.
 * Same English-prefix debt as `isInternalSubagentHandoffStatusItem` in
 * deepseek-runtime.ts — prefer a `visibility: internal` field when that lands.
 */
export function isInternalSubagentHandoffSystemText(text: string | undefined): boolean {
  const trimmed = text?.trim() ?? ''
  return /^(?:Resuming turn with \d+ sub-agent|Waiting on \d+ sub-agent)/i.test(trimmed)
}

type AssistantContentBlock = Extract<ChatBlock, { kind: 'assistant' }>

/** Reasoning / mid-turn preface rows that may own the live Square Grid. */
function isThinkingIndicatorBlock(block: ChatBlock): boolean {
  if (block.kind === 'reasoning') return true
  if (block.kind !== 'assistant') return false
  return block.agentSegment === 'mid_turn_preface' || block.agentSegment == null
}

export type RenderRow =
  | { type: 'block'; block: ChatBlock }
  | { type: 'tool_batch'; toolName: string; blocks: ToolProcessBlock[]; mixed?: boolean }

/**
 * Id of the sole process-rail row allowed to show a live thinking glyph.
 * Null when the turn is idle, or when later work (another thought / tools)
 * has already superseded the previous thinking step.
 */
export function trailingThinkingIndicatorId(
  rows: RenderRow[],
  processing: boolean
): string | null {
  if (!processing) return null
  let sawLaterWork = false
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const row = rows[i]!
    if (row.type === 'tool_batch') {
      sawLaterWork = true
      continue
    }
    if (isThinkingIndicatorBlock(row.block)) {
      return sawLaterWork ? null : row.block.id
    }
    sawLaterWork = true
  }
  return null
}

export function placeAssistantContentBlock(
  block: AssistantContentBlock,
  contentBlock: AssistantContentBlock,
  nextProcessBlocks: ChatBlock[],
  nextAssistantContentBlocks: AssistantContentBlock[]
): void {
  // Route purely on the persisted segment metadata. The runtime tags every
  // agent_message; anything untagged (legacy threads) stays in the work trace
  // rather than being promoted to an answer by position or text shape.
  if (block.agentSegment === 'final_answer') {
    nextAssistantContentBlocks.push(contentBlock)
    return
  }
  nextProcessBlocks.push(contentBlock)
}

export function reasoningDetailTextFromBlocks(blocks: ChatBlock[]): string {
  if (reasoningNarrationFromBlocks(blocks)) return ''
  return blocks
    .filter(
      (block): block is Extract<ChatBlock, { kind: 'reasoning' }> => block.kind === 'reasoning'
    )
    .map((block) => block.text.trim())
    .filter(Boolean)
    .join('\n\n')
}

export function reasoningNarrationFromBlocks(blocks: ChatBlock[]): string {
  for (const block of blocks) {
    if (block.kind === 'reasoning' && block.narration?.trim()) {
      return block.narration.trim()
    }
  }
  return ''
}

/** Raw command text for shell probe classification (full, not truncated). */
function commandTextFromToolBlock(block: ToolProcessBlock): string | undefined {
  const raw = block.meta?.tool_input
  if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
    for (const key of ['command', 'cmd', 'script'] as const) {
      const value = (raw as Record<string, unknown>)[key]
      if (typeof value === 'string' && value.trim()) return value.trim()
    }
  }
  const metaCmd = block.meta?.command
  if (typeof metaCmd === 'string' && metaCmd.trim()) return metaCmd.trim()
  const match = /^[a-z0-9_-]+\s*:\s*(.+)$/i.exec(block.summary.trim())
  return match?.[1]?.trim() || undefined
}

/**
 * Whether a process block is a read-only probe that can fold into a batch.
 * Aligned with StepFlow: success / running / error probes merge (including
 * allowlisted probe shells); mutations, interactive/mutating shell, todo,
 * and subagent-orchestration stay solo.
 */
function isMergeableProbeBlock(block: ChatBlock): block is ToolProcessBlock {
  if (block.kind !== 'tool') return false
  if (
    block.status !== 'success' &&
    block.status !== 'running' &&
    block.status !== 'error'
  ) {
    return false
  }
  if (block.toolKind === 'file_change') return false
  const name = toolNameFromProcessBlock(block)
  if (isTodoToolBlock(block)) return false
  if (isSubagentOrchestrationToolName(name)) return false
  return isMergeableProbeTool(name, { command: commandTextFromToolBlock(block) })
}

/**
 * Fold consecutive settled read-only probes into one `tool_batch`, including
 * mixed read/search/grep runs (same rule as Task/SubAgent StepFlow). A lone
 * probe stays a plain block; non-mergeable rows end the current run.
 */
export function groupProcessRows(visible: ChatBlock[]): RenderRow[] {
  const rows: RenderRow[] = []
  let buffer: ToolProcessBlock[] = []

  const flush = (): void => {
    if (buffer.length >= 2) {
      const names = new Set(buffer.map((b) => toolNameFromProcessBlock(b).toLowerCase()))
      const mixed = names.size > 1
      const toolName = mixed ? 'probe' : [...names][0] || toolNameFromProcessBlock(buffer[0]!)
      rows.push({ type: 'tool_batch', toolName, blocks: buffer, mixed })
    } else if (buffer.length === 1) {
      rows.push({ type: 'block', block: buffer[0]! })
    }
    buffer = []
  }

  for (const block of visible) {
    if (isMergeableProbeBlock(block)) {
      buffer.push(block)
      continue
    }
    flush()
    rows.push({ type: 'block', block })
  }
  flush()
  return rows
}

/** Count tool / batch rows for the compact “N 步” chrome (skip narration). */
export function countSubagentRailSteps(items: StepFlowItem[]): number {
  return items.filter((i) => {
    if (i.variant === 'narration') return false
    if (i.variant === 'batch') return true
    return Boolean(i.toolName)
  }).length
}

/** Soft cap for process-rail mid-turn prefaces (one short storyline line). */
export const MID_TURN_PREFACE_MAX_CHARS = 160

/** Clip a mid-turn preface for the process rail; full text stays expand-able. */
export function clipMidTurnPrefaceText(
  text: string,
  maxChars: number = MID_TURN_PREFACE_MAX_CHARS
): { preview: string; clipped: boolean } {
  const trimmed = text.trim()
  if (!trimmed) return { preview: '', clipped: false }

  // Prefer the first line when the model dumps a multi-line mini-report.
  const firstLine = trimmed.split(/\n/, 1)[0] ?? trimmed
  const source =
    firstLine.length > 0 && firstLine.length < trimmed.length ? firstLine : trimmed

  if (source === trimmed && source.length <= maxChars) {
    return { preview: trimmed, clipped: false }
  }

  let cut = source.length <= maxChars ? source : source.slice(0, maxChars)
  if (cut.length < source.length) {
    const ws = cut.lastIndexOf(' ')
    if (ws >= Math.floor(maxChars * 0.6)) cut = cut.slice(0, ws)
  }
  return { preview: `${cut.trimEnd()}…`, clipped: true }
}
