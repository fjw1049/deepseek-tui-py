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
import {
  addProbeCompose,
  emptyProbeCompose,
  isMergeableProbeTool,
  probeToolKind,
  type ProbeBatchCompose
} from '../../lib/step-flow-collapse'
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
 * mixed read/search/grep runs and a lone probe (“读取文件 · 1 项”).
 * Non-mergeable rows end the current run.
 */
export function groupProcessRows(visible: ChatBlock[]): RenderRow[] {
  const rows: RenderRow[] = []
  let buffer: ToolProcessBlock[] = []

  const flush = (): void => {
    if (buffer.length >= 1) {
      const names = new Set(buffer.map((b) => toolNameFromProcessBlock(b).toLowerCase()))
      const mixed = names.size > 1
      const toolName = mixed ? 'probe' : [...names][0] || toolNameFromProcessBlock(buffer[0]!)
      rows.push({ type: 'tool_batch', toolName, blocks: buffer, mixed })
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

/**
 * Incomplete-markdown parsing belongs only on the live answer bubble.
 * Settled process-rail text must stay static or unclosed `**` / `` ` ``
 * get promoted into fake fenced blocks mid-turn.
 */
export function shouldParseIncompleteAssistantMarkdown(isLiveAnswer: boolean): boolean {
  return isLiveAnswer
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

export function processRowId(row: RenderRow): string {
  return row.type === 'tool_batch' ? `batch:${row.blocks[0]!.id}` : row.block.id
}

function isRunningWorkRow(row: RenderRow): boolean {
  if (row.type === 'tool_batch') return row.blocks.some((block) => block.status === 'running')
  return row.block.kind === 'tool' && row.block.status === 'running'
}

function hasErrorWorkRow(row: RenderRow): boolean {
  if (row.type === 'tool_batch') return row.blocks.some((block) => block.status === 'error')
  return row.block.kind === 'tool' && row.block.status === 'error'
}

function isQueuedWorkRow(row: RenderRow): boolean {
  if (row.type === 'tool_batch') {
    return row.blocks.some((block) => block.status === 'queued' || block.status === 'pending')
  }
  return (
    row.block.kind === 'tool' && (row.block.status === 'queued' || row.block.status === 'pending')
  )
}

/** Work rows that may fold into a mid-turn “Ran N…” summary. */
export function isSummarizableWorkRow(row: RenderRow): boolean {
  if (isRunningWorkRow(row) || hasErrorWorkRow(row) || isQueuedWorkRow(row)) return false
  if (row.type === 'tool_batch') return true
  if (row.block.kind !== 'tool') return false
  if (isTodoToolBlock(row.block)) return false
  return !isSubagentOrchestrationToolName(toolNameFromProcessBlock(row.block))
}

function summarizableUnitCount(row: RenderRow): number {
  return row.type === 'tool_batch' ? row.blocks.length : 1
}

/** Newest tool / batch row — the only work that stays expanded while the turn is live. */
export function findLastLiveWorkRowId(
  rows: ReadonlyArray<RenderRow>,
  processing: boolean
): string | null {
  if (!processing) return null
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const row = rows[i]!
    if (row.type === 'tool_batch' || row.block.kind === 'tool') {
      return processRowId(row)
    }
  }
  return null
}

export type ProcessWorkSummary = {
  compose: ProbeBatchCompose
  editCount: number
  toolCount: number
}

export type ProcessRenderChunk =
  | { type: 'row'; row: RenderRow }
  | { type: 'work_summary'; id: string; rows: RenderRow[]; summary: ProcessWorkSummary }

const MIN_COLLAPSIBLE_WORK_UNITS = 2

function summarizeWorkRows(rows: ReadonlyArray<RenderRow>): ProcessWorkSummary {
  const compose = emptyProbeCompose()
  let editCount = 0
  let toolCount = 0
  for (const row of rows) {
    if (row.type === 'tool_batch') {
      for (const block of row.blocks) {
        addProbeCompose(compose, probeToolKind(toolNameFromProcessBlock(block)))
      }
      continue
    }
    if (row.block.kind !== 'tool') continue
    if (row.block.toolKind === 'file_change') {
      editCount += 1
      continue
    }
    const name = toolNameFromProcessBlock(row.block)
    if (isMergeableProbeTool(name, { command: commandTextFromToolBlock(row.block) })) {
      addProbeCompose(compose, probeToolKind(name))
      continue
    }
    if (row.block.toolKind === 'command_execution') {
      addProbeCompose(compose, 'command')
      continue
    }
    toolCount += 1
  }
  return { compose, editCount, toolCount }
}

/**
 * During a live turn, fold older settled work into one summary so the process
 * rail does not keep growing. The trailing work row stays expanded. Settled
 * turns (`processing=false`) return every row unchanged — the WorkMetaRow
 * already hides the whole rail.
 */
export function planProcessRenderChunks(
  rows: ReadonlyArray<RenderRow>,
  processing: boolean
): ProcessRenderChunk[] {
  if (!processing) return rows.map((row) => ({ type: 'row' as const, row }))

  const lastLiveId = findLastLiveWorkRowId(rows, true)
  const chunks: ProcessRenderChunk[] = []
  let buffer: RenderRow[] = []

  const flush = (): void => {
    if (buffer.length === 0) return
    const units = buffer.reduce((count, row) => count + summarizableUnitCount(row), 0)
    if (units >= MIN_COLLAPSIBLE_WORK_UNITS) {
      chunks.push({
        type: 'work_summary',
        id: processRowId(buffer[0]!),
        rows: buffer,
        summary: summarizeWorkRows(buffer)
      })
    } else {
      for (const row of buffer) chunks.push({ type: 'row', row })
    }
    buffer = []
  }

  for (const row of rows) {
    const canFold = isSummarizableWorkRow(row) && processRowId(row) !== lastLiveId
    if (canFold) {
      buffer.push(row)
      continue
    }
    flush()
    chunks.push({ type: 'row', row })
  }
  flush()
  return chunks
}

export const TAIL_ANCHOR_TOP_INSET_PX = 16
export const TAIL_ANCHOR_RELEASE_SLACK_PX = 8

/** Extra space below the live turn so the sent user bubble can sit at the top. */
export function computeTailAnchorSpacerPx(input: {
  viewportHeight: number
  topInset?: number
  userHeight: number
  contentAfterUser: number
}): number {
  const topInset = input.topInset ?? TAIL_ANCHOR_TOP_INSET_PX
  const roomBelowUser = input.viewportHeight - topInset - input.userHeight
  if (![roomBelowUser, input.contentAfterUser].every(Number.isFinite)) return 0
  return Math.max(0, roomBelowUser - Math.max(0, input.contentAfterUser))
}

export function computeTailAnchorScrollTop(input: {
  userOffsetTop: number
  topInset?: number
}): number {
  const topInset = input.topInset ?? TAIL_ANCHOR_TOP_INSET_PX
  if (![input.userOffsetTop, topInset].every(Number.isFinite)) return 0
  return Math.max(0, input.userOffsetTop - topInset)
}

export function shouldReleaseTailAnchor(input: {
  spacerPx: number
  userScrolled: boolean
  slackPx?: number
}): boolean {
  if (input.userScrolled) return true
  const slack = input.slackPx ?? TAIL_ANCHOR_RELEASE_SLACK_PX
  return input.spacerPx <= slack
}
