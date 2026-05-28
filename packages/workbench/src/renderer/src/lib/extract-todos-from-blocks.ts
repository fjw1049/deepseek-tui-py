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

export type TodoTurnSession = {
  anchorBlockId: string
  todoBlockIds: string[]
  items: TodoItemView[]
  completionPct: number
  inProgressId: string | null
  isComplete: boolean
}

const TODO_TOOL_RE = /(?:todo|checklist)_(?:write|update|add|list)/i
const TODO_WRITE_RE = /(?:todo|checklist)_write$/i

export function isTodoToolName(name: string | undefined): boolean {
  if (!name) return false
  return TODO_TOOL_RE.test(name)
}

function isTodoWriteToolName(name: string | undefined): boolean {
  if (!name) return false
  return TODO_WRITE_RE.test(name)
}

function summaryLooksTodo(summary: string): boolean {
  return (
    /\b(?:todo|checklist)_(?:write|update|add|list)\b/i.test(summary) ||
    /\bitems written\b/i.test(summary)
  )
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

export function toolNameFromTodoBlock(block: Extract<ChatBlock, { kind: 'tool' }>): string | undefined {
  const metaName = typeof block.meta?.tool_name === 'string' ? block.meta.tool_name : undefined
  if (metaName) return metaName
  const summary = block.summary.trim()
  const head = summary.split(/[:(]/, 1)[0]?.trim()
  return head || undefined
}

export function parseTodoItemsFromBlock(block: Extract<ChatBlock, { kind: 'tool' }>): TodoItemView[] | null {
  return (
    parseItemsFromMeta(block.meta) ??
    parseItemsFromToolArguments(block.detail) ??
    parseItemsFromDetail(block.detail) ??
    null
  )
}

export function isTodoToolBlock(block: ChatBlock): block is Extract<ChatBlock, { kind: 'tool' }> {
  if (block.kind !== 'tool') return false
  const toolName = toolNameFromTodoBlock(block)
  return isTodoToolName(toolName) || summaryLooksTodo(block.summary)
}

function snapshotFromItems(items: TodoItemView[]): Omit<TodoSidebarSnapshot, never> {
  const completed = items.filter((item) => item.status === 'completed').length
  const completionPct = items.length ? Math.round((completed * 100) / items.length) : 0
  const inProgress = items.find((item) => item.status === 'in_progress')
  return {
    items,
    completionPct,
    inProgressId: inProgress?.id ?? null
  }
}

function mergeTodoUpdate(items: TodoItemView[], block: Extract<ChatBlock, { kind: 'tool' }>): TodoItemView[] {
  const parsed = parseTodoItemsFromBlock(block)
  if (parsed?.length) return parsed

  const itemId =
    (typeof block.meta?.item_id === 'string' && block.meta.item_id) ||
    (typeof block.meta?.itemId === 'string' && block.meta.itemId) ||
    undefined
  const nextStatus = normalizeStatus(block.meta?.status)
  if (!itemId) return items

  return items.map((item) =>
    item.id === itemId ? { ...item, status: nextStatus } : item
  )
}

export function buildTodoSessionForTurn(blocks: ChatBlock[]): TodoTurnSession | null {
  let anchorBlockId: string | null = null
  let items: TodoItemView[] = []
  const todoBlockIds: string[] = []

  for (const block of blocks) {
    if (!isTodoToolBlock(block)) continue

    todoBlockIds.push(block.id)
    const toolName = toolNameFromTodoBlock(block)
    const parsed = parseTodoItemsFromBlock(block)

    if (isTodoWriteToolName(toolName)) {
      if (parsed?.length) {
        items = parsed
        if (!anchorBlockId) anchorBlockId = block.id
      } else if (!anchorBlockId) {
        anchorBlockId = block.id
      }
      continue
    }

    if (!anchorBlockId) anchorBlockId = block.id

    if (parsed?.length) {
      items = parsed
      continue
    }

    if (/(?:todo|checklist)_add$/i.test(toolName ?? '')) {
      continue
    }

    if (/(?:todo|checklist)_update$/i.test(toolName ?? '')) {
      items = mergeTodoUpdate(items, block)
    }
  }

  if (!anchorBlockId || items.length === 0) return null

  const snapshot = snapshotFromItems(items)
  const isComplete = snapshot.items.every((item) => item.status === 'completed')

  return {
    anchorBlockId,
    todoBlockIds,
    items: snapshot.items,
    completionPct: snapshot.completionPct,
    inProgressId: snapshot.inProgressId,
    isComplete
  }
}

export function extractTodosFromBlocks(blocks: ChatBlock[]): TodoSidebarSnapshot | null {
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index]
    if (!isTodoToolBlock(block)) continue
    const items = parseTodoItemsFromBlock(block)
    if (!items?.length) continue
    return snapshotFromItems(items)
  }
  return null
}
