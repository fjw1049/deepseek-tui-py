/** Local kanban UI state: unsent drafts + manual draft column order. */

const DRAFTS_KEY = 'deepseekgui.kanban.draftPrompts'
const DRAFT_ORDERS_KEY = 'deepseekgui.kanban.draftOrders'

export type KanbanDraftRecord = {
  prompt: string
  model?: string
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
      out[key] = model ? { prompt, model } : { prompt }
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
  draft: { prompt: string; model?: string } | null
): void {
  const id = threadId.trim()
  if (!id) return
  const next = loadKanbanDrafts()
  const prompt = draft?.prompt.trim() ?? ''
  if (!prompt) {
    delete next[id]
  } else {
    const model = draft?.model?.trim()
    next[id] = model ? { prompt, model } : { prompt }
  }
  writeJson(DRAFTS_KEY, next)
}

export function setKanbanDraftPrompt(threadId: string, prompt: string, model?: string): void {
  const trimmed = prompt.trim()
  if (!trimmed) {
    setKanbanDraft(threadId, null)
    return
  }
  setKanbanDraft(threadId, { prompt: trimmed, ...(model?.trim() ? { model: model.trim() } : {}) })
}

export function clearKanbanDraftPrompt(threadId: string): void {
  setKanbanDraft(threadId, null)
}

export function loadKanbanDraftOrders(): Record<string, string[]> {
  return readStringArrayRecord(DRAFT_ORDERS_KEY)
}

export function setKanbanDraftOrder(projectId: string, cardIds: string[]): void {
  const id = projectId.trim()
  if (!id) return
  const next = loadKanbanDraftOrders()
  next[id] = cardIds
  writeJson(DRAFT_ORDERS_KEY, next)
}
