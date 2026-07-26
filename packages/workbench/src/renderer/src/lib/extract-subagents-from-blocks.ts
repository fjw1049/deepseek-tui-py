import type { ChatBlock } from '../agent/types'
import { humanizeAgentType } from './agent-type-label'

export type DockSubagentStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export type DockSubagentItem = {
  id: string
  agentId: string
  agentType: string
  /** Spawn assignment preview when mailbox ``started`` or spawn tool carried it. */
  prompt?: string
  status: DockSubagentStatus
}

export function isActiveSubagentStatus(status: DockSubagentStatus): boolean {
  return status === 'pending' || status === 'running'
}

/** One-line title for dock / summary rows — prefer spawn prompt over type labels. */
export function subagentListTitle(
  item: Pick<DockSubagentItem, 'agentId' | 'agentType' | 'prompt'>,
  maxChars = 56,
  typeFallback = ''
): string {
  const prompt = (item.prompt || '').replace(/\s+/g, ' ').trim()
  if (prompt) {
    if (prompt.length <= maxChars) return prompt
    return `${prompt.slice(0, Math.max(maxChars - 1, 1)).trimEnd()}…`
  }
  const typeLabel = humanizeAgentType(item.agentType) || typeFallback
  if (typeLabel) return typeLabel
  const short = item.agentId.replace(/^agent_/, '')
  return short.length > 0 && short.length < item.agentId.length
    ? `Subagent ${short.slice(0, 8)}`
    : item.agentId
}

function toolNameFromBlock(block: Extract<ChatBlock, { kind: 'tool' }>): string {
  const metaName = typeof block.meta?.tool_name === 'string' ? block.meta.tool_name.trim() : ''
  if (metaName) return metaName
  const head = block.summary.trim().split(/[:(]/, 1)[0]?.trim()
  return head || ''
}

/** Resolve spawn ``agent_id`` from tool metadata or ``spawned <id>`` result text. */
function agentIdFromSpawnTool(block: Extract<ChatBlock, { kind: 'tool' }>): string {
  const metaId = typeof block.meta?.agent_id === 'string' ? block.meta.agent_id.trim() : ''
  if (metaId) return metaId
  const text = `${block.detail || ''}\n${block.summary || ''}`
  const match = /\bspawned\s+(agent_[A-Za-z0-9_-]+)/i.exec(text)
  return match?.[1] ?? ''
}

/**
 * Map ``agent_id → spawn prompt`` from completed (or in-flight) ``agent`` tool
 * rows. Mailbox ``started.prompt`` is preferred when present on the card; this
 * backfills the common case where only the parent tool call carries the text.
 */
export function collectSpawnPromptsByAgentId(blocks: ChatBlock[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const block of blocks) {
    if (block.kind !== 'tool' || !block.meta) continue
    const input = block.meta.tool_input
    if (!input || typeof input !== 'object' || Array.isArray(input)) continue
    const rec = input as Record<string, unknown>
    const action = typeof rec.action === 'string' ? rec.action.trim().toLowerCase() : ''
    const toolName = toolNameFromBlock(block).toLowerCase()
    const isSpawn =
      action === 'spawn' ||
      toolName === 'agent_spawn' ||
      toolName.endsWith('_spawn') ||
      toolName === 'spawn_agent'
    if (!isSpawn) continue
    // Merged `agent` tool without action=spawn is wait/result/etc.
    if (toolName === 'agent' && action !== 'spawn') continue

    const agentId = agentIdFromSpawnTool(block)
    const prompt = typeof rec.prompt === 'string' ? rec.prompt.replace(/\s+/g, ' ').trim() : ''
    if (!agentId || !prompt) continue
    out[agentId] = prompt
  }
  return out
}

/** Fill missing ``subagent.prompt`` from sibling spawn tool metadata. */
export function applySpawnPromptsToSubagentBlocks(blocks: ChatBlock[]): ChatBlock[] {
  const prompts = collectSpawnPromptsByAgentId(blocks)
  if (Object.keys(prompts).length === 0) return blocks
  let changed = false
  const next = blocks.map((block) => {
    if (block.kind !== 'subagent') return block
    if (typeof block.prompt === 'string' && block.prompt.trim()) return block
    const prompt = prompts[block.agentId]
    if (!prompt) return block
    changed = true
    return { ...block, prompt }
  })
  return changed ? next : blocks
}

/** Conversation subagent cards for the operation dock (display-only). */
export function extractSubagentsFromBlocks(blocks: ChatBlock[]): DockSubagentItem[] {
  const spawnPrompts = collectSpawnPromptsByAgentId(blocks)
  const out: DockSubagentItem[] = []
  for (const block of blocks) {
    if (block.kind !== 'subagent') continue
    const prompt =
      (typeof block.prompt === 'string' ? block.prompt.trim() : '') ||
      spawnPrompts[block.agentId] ||
      ''
    out.push({
      id: block.id,
      agentId: block.agentId,
      agentType: block.agentType,
      ...(prompt ? { prompt } : {}),
      status: block.status
    })
  }
  return out
}
