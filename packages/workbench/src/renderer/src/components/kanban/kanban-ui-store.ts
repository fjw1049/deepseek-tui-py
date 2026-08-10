/** Local kanban UI state: unsent drafts + manual column card order. */

import type { ApprovalPolicy } from '@shared/app-settings'
import type { KanbanColumnKey } from './kanban.logic'

const DRAFTS_KEY = 'deepseekgui.kanban.draftPrompts'
const DRAFT_ORDERS_KEY = 'deepseekgui.kanban.draftOrders'
const COLUMN_ORDERS_KEY = 'deepseekgui.kanban.columnOrders'

export type KanbanColumnOrders = Partial<Record<KanbanColumnKey, string[]>>

/** Same three product tiers as the composer approval picker. */
export type KanbanApprovalPolicy = Extract<ApprovalPolicy, 'on-request' | 'untrusted' | 'auto'>

export const DEFAULT_KANBAN_APPROVAL_POLICY: KanbanApprovalPolicy = 'auto'

export type KanbanDraftRecord = {
  prompt: string
  model?: string
  approvalPolicy?: KanbanApprovalPolicy
}

export function normalizeKanbanApprovalPolicy(value: unknown): KanbanApprovalPolicy | undefined {
  if (value === 'auto' || value === 'untrusted' || value === 'on-request') return value
  return undefined
}

export function kanbanExecutionFlags(policy: KanbanApprovalPolicy): {
  auto_approve: boolean
  trust_mode: boolean
} {
  const auto = policy === 'auto'
  return { auto_approve: auto, trust_mode: auto }
}

function readStringArrayRecord(key: string): Record<string, string[]> {
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const out: Record<string, string[]> = {}
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (!Array.isArray(v)) continue
      out[k] = v.filter((id): id is string => typeof id === 'string' && id.trim().length > 0)
    }
    return out
  } catch {
    return {}
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* private window / quota */
  }
}

/** Supports legacy `Record<threadId, prompt>` and current `{ prompt, model? }`. */
export function loadKanbanDrafts(): Record<string, KanbanDraftRecord> {
  try {
    const raw = window.localStorage.getItem(DRAFTS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const out: Record<string, KanbanDraftRecord> = {}
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof value === 'string' && value.trim()) {
        out[key] = { prompt: value.trim() }
        continue
      }
      if (!value || typeof value !== 'object' || Array.isArray(value)) continue
      const row = value as Record<string, unknown>
      const prompt = typeof row.prompt === 'string' ? row.prompt.trim() : ''
      if (!prompt) continue
      const model = typeof row.model === 'string' ? row.model.trim() : ''
      const approvalPolicy = normalizeKanbanApprovalPolicy(row.approvalPolicy)
      out[key] = {
        prompt,
        ...(model ? { model } : {}),
        ...(approvalPolicy ? { approvalPolicy } : {})
      }
    }
    return out
  } catch {
    return {}
  }
}

/** Prompt-only projection for board column derivation. */
export function loadKanbanDraftPrompts(): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [id, draft] of Object.entries(loadKanbanDrafts())) {
    out[id] = draft.prompt
  }
  return out
}

export function setKanbanDraft(
  threadId: string,
  draft: {
    prompt: string
    model?: string
    approvalPolicy?: KanbanApprovalPolicy
  } | null
): void {
  const id = threadId.trim()
  if (!id) return
  const next = loadKanbanDrafts()
  const prompt = draft?.prompt.trim() ?? ''
  if (!prompt) {
    delete next[id]
  } else {
    const model = draft?.model?.trim()
    const approvalPolicy =
      normalizeKanbanApprovalPolicy(draft?.approvalPolicy) ?? DEFAULT_KANBAN_APPROVAL_POLICY
    next[id] = {
      prompt,
      ...(model ? { model } : {}),
      approvalPolicy
    }
  }
  writeJson(DRAFTS_KEY, next)
}

export function setKanbanDraftPrompt(
  threadId: string,
  prompt: string,
  model?: string,
  approvalPolicy?: KanbanApprovalPolicy
): void {
  const trimmed = prompt.trim()
  if (!trimmed) {
    setKanbanDraft(threadId, null)
    return
  }
  setKanbanDraft(threadId, {
    prompt: trimmed,
    ...(model?.trim() ? { model: model.trim() } : {}),
    approvalPolicy: approvalPolicy ?? DEFAULT_KANBAN_APPROVAL_POLICY
  })
}

export function clearKanbanDraftPrompt(threadId: string): void {
  setKanbanDraft(threadId, null)
}

function isKanbanColumnKey(value: unknown): value is KanbanColumnKey {
  return value === 'draft' || value === 'inProgress' || value === 'done'
}

/** Load per-project column orders; migrates legacy draft-only orders once. */
export function loadKanbanColumnOrders(): Record<string, KanbanColumnOrders> {
  try {
    const raw = window.localStorage.getItem(COLUMN_ORDERS_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as unknown
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
      const out: Record<string, KanbanColumnOrders> = {}
      for (const [projectId, value] of Object.entries(parsed as Record<string, unknown>)) {
        if (!value || typeof value !== 'object' || Array.isArray(value)) continue
        const row = value as Record<string, unknown>
        const orders: KanbanColumnOrders = {}
        for (const [column, ids] of Object.entries(row)) {
          if (!isKanbanColumnKey(column) || !Array.isArray(ids)) continue
          const cleaned = ids.filter(
            (id): id is string => typeof id === 'string' && id.trim().length > 0
          )
          if (cleaned.length > 0) orders[column] = cleaned
        }
        if (Object.keys(orders).length > 0) out[projectId] = orders
      }
      return out
    }
  } catch {
    /* fall through to legacy */
  }

  const legacyDraft = readStringArrayRecord(DRAFT_ORDERS_KEY)
  const migrated: Record<string, KanbanColumnOrders> = {}
  for (const [projectId, ids] of Object.entries(legacyDraft)) {
    if (ids.length > 0) migrated[projectId] = { draft: ids }
  }
  if (Object.keys(migrated).length > 0) {
    writeJson(COLUMN_ORDERS_KEY, migrated)
  }
  return migrated
}

export function setKanbanColumnOrder(
  projectId: string,
  column: KanbanColumnKey,
  cardIds: string[]
): void {
  const id = projectId.trim()
  if (!id) return
  const next = loadKanbanColumnOrders()
  const current = { ...(next[id] ?? {}) }
  if (cardIds.length === 0) {
    delete current[column]
  } else {
    current[column] = cardIds
  }
  if (Object.keys(current).length === 0) {
    delete next[id]
  } else {
    next[id] = current
  }
  writeJson(COLUMN_ORDERS_KEY, next)
}

/** @deprecated Prefer {@link loadKanbanColumnOrders}. */
export function loadKanbanDraftOrders(): Record<string, string[]> {
  const orders = loadKanbanColumnOrders()
  const out: Record<string, string[]> = {}
  for (const [projectId, columns] of Object.entries(orders)) {
    if (columns.draft?.length) out[projectId] = columns.draft
  }
  return out
}

/** @deprecated Prefer {@link setKanbanColumnOrder}. */
export function setKanbanDraftOrder(projectId: string, cardIds: string[]): void {
  setKanbanColumnOrder(projectId, 'draft', cardIds)
}
