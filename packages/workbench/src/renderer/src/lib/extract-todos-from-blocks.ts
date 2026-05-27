import type { ChatBlock } from '../agent/types'

export type TodoItemView = {
  id: string
  content: string
  status: 'pending' | 'in_progress' | 'completed'
}

export type TodoSidebarSnapshot = {
  items: TodoItemView[]
  completionPct: number
  inProgressId: string | null
}

const TODO_TOOL_RE = /(?:todo|checklist)_(?:write|update|add|list)/i

function isTodoToolName(name: string | undefined): boolean {
  if (!name) return false
  return TODO_TOOL_RE.test(name)
}

function normalizeStatus(raw: unknown): TodoItemView['status'] {
  if (typeof raw !== 'string') return 'pending'
  const s = raw.trim().toLowerCase()
  if (s === 'completed' || s === 'done') return 'completed'
  if (s === 'in_progress' || s === 'inprogress' || s === 'in-progress') return 'in_progress'
  return 'pending'
}

function parseItemsFromMeta(meta: Record<string, unknown> | undefined): TodoItemView[] | null {
  if (!meta) return null
  const taskUpdates = meta.task_updates
  if (taskUpdates && typeof taskUpdates === 'object') {
    const checklist = (taskUpdates as Record<string, unknown>).checklist
    if (checklist && typeof checklist === 'object') {
      const fromChecklist = parseItemsArray((checklist as Record<string, unknown>).items)
      if (fromChecklist) return fromChecklist
    }
  }
  return parseItemsArray(meta.items)
}

function parseItemsArray(raw: unknown): TodoItemView[] | null {
  if (!Array.isArray(raw) || raw.length === 0) return null
  const items: TodoItemView[] = []
  for (const entry of raw) {
    if (typeof entry === 'string' && entry.trim()) {
      items.push({ id: String(items.length + 1), content: entry.trim(), status: 'pending' })
      continue
    }
    if (!entry || typeof entry !== 'object') continue
    const row = entry as Record<string, unknown>
    const content =
      (typeof row.content === 'string' && row.content.trim()) ||
      (typeof row.text === 'string' && row.text.trim()) ||
      ''
    if (!content) continue
    const id = row.id != null ? String(row.id) : String(items.length + 1)
    items.push({ id, content, status: normalizeStatus(row.status) })
  }
  return items.length > 0 ? items : null
}

function parseItemsFromToolArguments(detail: string | undefined): TodoItemView[] | null {
  if (!detail?.trim()) return null
  const trimmed = detail.trim()
  if (!(trimmed.startsWith('{') || trimmed.startsWith('['))) return null
  try {
    const parsed = JSON.parse(trimmed) as Record<string, unknown>
    return parseItemsArray(parsed.todos) ?? parseItemsArray(parsed.items)
  } catch {
    return null
  }
}

function parseItemsFromDetail(detail: string | undefined): TodoItemView[] | null {
  if (!detail?.trim()) return null
  const lines = detail.split('\n').map((line) => line.trim()).filter(Boolean)
  const items: TodoItemView[] = []
  for (const line of lines) {
    const match = line.match(/^\[( |x|~)\]\s*(?:#\d+\s*)?(.+)$/i)
    if (!match) continue
    const mark = match[1].toLowerCase()
    const status: TodoItemView['status'] =
      mark === 'x' ? 'completed' : mark === '~' ? 'in_progress' : 'pending'
    items.push({ id: String(items.length + 1), content: match[2].trim(), status })
  }
  return items.length > 0 ? items : null
}

function toolNameFromBlock(block: Extract<ChatBlock, { kind: 'tool' }>): string | undefined {
  const metaName = typeof block.meta?.tool_name === 'string' ? block.meta.tool_name : undefined
  if (metaName) return metaName
  const summary = block.summary.trim()
  const head = summary.split(/[:(]/, 1)[0]?.trim()
  return head || undefined
}

function activeTodos(items: TodoItemView[]): TodoItemView[] {
  return items.filter((item) => item.status === 'pending' || item.status === 'in_progress')
}

export function extractTodosFromBlocks(blocks: ChatBlock[]): TodoSidebarSnapshot | null {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index]
    if (block.kind !== 'tool') continue
    const toolName = toolNameFromBlock(block)
    const summaryLooksTodo =
      /\b(?:todo|checklist)_(?:write|update|add|list)\b/i.test(block.summary) ||
      /\bitems written\b/i.test(block.summary)
    if (!isTodoToolName(toolName) && !summaryLooksTodo) continue
    const items =
      parseItemsFromMeta(block.meta) ??
      parseItemsFromToolArguments(block.detail) ??
      parseItemsFromDetail(block.detail) ??
      null
    if (!items?.length) continue
    const active = activeTodos(items)
    const completed = items.filter((item) => item.status === 'completed').length
    const completionPct = items.length ? Math.round((completed * 100) / items.length) : 0
    const inProgress = items.find((item) => item.status === 'in_progress')
    return {
      items: active.length > 0 ? active : items,
      completionPct,
      inProgressId: inProgress?.id ?? null
    }
  }
  return null
}
