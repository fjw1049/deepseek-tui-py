import type { ChatBlock } from '../agent/types'
import {
  DEFAULT_COMPOSER_MODEL,
  DEFAULT_COMPOSER_MODEL_IDS
} from '@shared/default-composer-models'
import type { ChatState } from './chat-store-types'
import { decodeModelRef } from '@shared/model-ref'

const COMPOSER_MODEL_STORAGE_KEY = 'deepseekgui.composerModel'
const TURN_MODEL_STORAGE_KEY = 'deepseekgui.turnModelLabel'
const PINNED_THREADS_STORAGE_KEY = 'deepseekgui.pinnedThreads'

export const PINNED_THREADS_LIMIT = 10

export function readStoredComposerModel(allowedIds: readonly string[]): string {
  try {
    const raw = localStorage.getItem(COMPOSER_MODEL_STORAGE_KEY)
    if (raw === null) return DEFAULT_COMPOSER_MODEL
    if (raw === '') return DEFAULT_COMPOSER_MODEL
    if (allowedIds.includes(raw)) return raw
  } catch {
    /* ignore */
  }
  return DEFAULT_COMPOSER_MODEL
}

export function persistComposerModel(model: string): void {
  try {
    localStorage.setItem(COMPOSER_MODEL_STORAGE_KEY, model)
  } catch {
    /* ignore */
  }
}

export function mergeComposerPickList(upstreamOk: boolean, upstreamIds: string[]): string[] {
  const ordered = new Set<string>(DEFAULT_COMPOSER_MODEL_IDS)
  if (upstreamOk) {
    for (const id of upstreamIds) {
      const trimmed = id.trim()
      if (trimmed && trimmed !== 'auto') ordered.add(trimmed)
    }
  }
  const preferred = new Set<string>(DEFAULT_COMPOSER_MODEL_IDS)
  const tail = [...ordered].filter((id) => !preferred.has(id)).sort((a, b) => a.localeCompare(b))
  return [...DEFAULT_COMPOSER_MODEL_IDS, ...tail]
}

export function optimisticUserModelLabel(
  composerModel: string,
  threadModel: string | undefined
): string | undefined {
  const composer = composerModel.trim()
  if (composer) {
    const model = decodeModelRef(composer).modelId
    return model.toLowerCase() === 'auto' ? 'auto' : model
  }
  const model = threadModel?.trim()
  return model || undefined
}

export function rememberTurnModel(threadId: string, itemId: string, model: string): void {
  if (!threadId || !itemId || !model.trim()) return
  const key = `${threadId}|${itemId}`
  const map = loadTurnModelMap()
  if (map[key] === model) return
  map[key] = model
  saveTurnModelMap(map)
}

export function hydrateBlockModelLabels(threadId: string, blocks: ChatBlock[]): ChatBlock[] {
  const map = loadTurnModelMap()
  let changed = false
  const next = blocks.map((block) => {
    if (block.kind !== 'user') return block
    if (block.modelLabel) return block
    const label = map[`${threadId}|${block.id}`]
    if (!label) return block
    changed = true
    return { ...block, modelLabel: label }
  })
  return changed ? next : blocks
}

function loadTurnModelMap(): Record<string, string> {
  try {
    const raw = localStorage.getItem(TURN_MODEL_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      const out: Record<string, string> = {}
      for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
        if (typeof value === 'string' && value) out[key] = value
      }
      return out
    }
    return {}
  } catch {
    return {}
  }
}

function saveTurnModelMap(map: Record<string, string>): void {
  try {
    localStorage.setItem(TURN_MODEL_STORAGE_KEY, JSON.stringify(map))
  } catch {
    /* localStorage may be unavailable (private window, quota) */
  }
}

export function loadPinnedThreadIds(): string[] {
  try {
    const raw = localStorage.getItem(PINNED_THREADS_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.filter((id): id is string => typeof id === 'string' && id.length > 0)
  } catch {
    return []
  }
}

export function savePinnedThreadIds(ids: string[]): void {
  try {
    localStorage.setItem(PINNED_THREADS_STORAGE_KEY, JSON.stringify(ids))
  } catch {
    /* localStorage may be unavailable (private window, quota) */
  }
}
