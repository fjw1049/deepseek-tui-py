import type { ChatBlock } from '../agent/types'

export type ContextBreakdownJson = {
  system_prompt: number
  tool_definitions?: number
  tools: number
  mcp?: number
  skills?: number
  rules?: number
  conversation: number
  total: number
  window: number
  free: number
}

export type ContextUsageSnapshot = {
  usedTokens: number
  maxTokens: number
  percent: number
  level: 'ok' | 'high' | 'critical'
}

const DEFAULT_CONTEXT_WINDOW = 128_000

/** Fallback when runtime context API is unavailable (TUI-style buckets). */
export const ENGINE_SYSTEM_BASELINE_TOKENS = 600
export const ENGINE_TOOLS_BASELINE_TOKENS = 7800

export function contextBucketTokens(
  breakdown: ContextBreakdownJson,
  bucket: 'system_prompt' | 'tool_definitions' | 'mcp' | 'skills' | 'rules' | 'conversation'
): number {
  switch (bucket) {
    case 'tool_definitions':
      return Math.max(0, breakdown.tool_definitions ?? breakdown.tools ?? 0)
    case 'mcp':
      return Math.max(0, breakdown.mcp ?? 0)
    case 'skills':
      return Math.max(0, breakdown.skills ?? 0)
    case 'rules':
      return Math.max(0, breakdown.rules ?? 0)
    default:
      return Math.max(0, breakdown[bucket] ?? 0)
  }
}

function contextWindowForModel(model: string): number {
  const lower = model.trim().toLowerCase()
  if (!lower) return DEFAULT_CONTEXT_WINDOW
  const match = lower.match(/(?:^|[^a-z0-9])(\d{2,4})k(?:[^a-z0-9]|$)/)
  if (match) {
    const kilo = Number(match[1])
    if (kilo >= 8 && kilo <= 1024) return kilo * 1000
  }
  if (lower.includes('deepseek')) return DEFAULT_CONTEXT_WINDOW
  return DEFAULT_CONTEXT_WINDOW
}

function usageLevel(percent: number): ContextUsageSnapshot['level'] {
  if (percent >= 95) return 'critical'
  if (percent >= 85) return 'high'
  return 'ok'
}

export function snapshotFromContextBreakdown(
  breakdown: ContextBreakdownJson
): ContextUsageSnapshot {
  const usedTokens = Math.max(0, breakdown.total)
  const maxTokens = breakdown.window > 0 ? breakdown.window : DEFAULT_CONTEXT_WINDOW
  const percent =
    maxTokens > 0 ? Math.min(100, Math.max(0, (usedTokens / maxTokens) * 100)) : 0
  return { usedTokens, maxTokens, percent, level: usageLevel(percent) }
}

function blockTextLength(block: ChatBlock): number {
  switch (block.kind) {
    case 'user':
    case 'assistant':
    case 'reasoning':
    case 'system':
      return block.text.length
    case 'tool':
      return (block.detail?.length ?? 0) + block.summary.length
    case 'approval':
    case 'user_input':
    case 'subagent':
      return block.summary?.length ?? 0
    default:
      return 0
  }
}

/** Client-side fallback when GET /v1/threads/{id}/context is unavailable. */
export function estimateContextUsageFallback(
  blocks: ChatBlock[],
  model: string
): ContextUsageSnapshot {
  const conversationChars = blocks.reduce((sum, block) => sum + blockTextLength(block), 0)
  let usedTokens =
    ENGINE_SYSTEM_BASELINE_TOKENS +
    ENGINE_TOOLS_BASELINE_TOKENS +
    (conversationChars > 0 ? Math.ceil(conversationChars / 3) : 0)
  if (blocks.length > 0) {
    usedTokens += blocks.length * 12 + 48
  }
  const maxTokens = contextWindowForModel(model)
  const percent = Math.min(100, Math.max(0, (usedTokens / maxTokens) * 100))
  return { usedTokens, maxTokens, percent, level: usageLevel(percent) }
}

/** Client-side breakdown when GET /v1/threads/{id}/context is unavailable. */
export function fallbackContextBreakdown(
  blocks: ChatBlock[],
  model: string
): ContextBreakdownJson {
  const conversationChars = blocks.reduce((sum, block) => sum + blockTextLength(block), 0)
  let conversation =
    conversationChars > 0 ? Math.ceil(conversationChars / 3) : 0
  if (blocks.length > 0) {
    conversation += blocks.length * 12 + 48
  }
  const system_prompt = ENGINE_SYSTEM_BASELINE_TOKENS
  const tool_definitions = ENGINE_TOOLS_BASELINE_TOKENS
  const mcp = 0
  const skills = 0
  const rules = 0
  const tools = tool_definitions + mcp
  const total = system_prompt + tools + skills + rules + conversation
  const window = contextWindowForModel(model)
  const free = Math.max(0, window - total)
  return {
    system_prompt,
    tool_definitions,
    tools,
    mcp,
    skills,
    rules,
    conversation,
    total,
    window,
    free
  }
}

/** Match TUI ``/context`` and footer ``fmt_tokens`` (e.g. 33.4k, 8.5k). */
export function formatTokenCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`
  return String(value)
}

/** Percent column aligned with TUI ``/context`` (e.g. `` 17.0%``). */
export function formatBucketPercent(tokens: number, window: number): string {
  if (window <= 0) return '  -  '
  return `${((100 * tokens) / window).toFixed(1).padStart(5)}%`
}
