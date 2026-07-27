/** Manual sidebar list order (localStorage). Auto-sort until the user drags. */

export const CHATS_ORDER_STORAGE_KEY = 'deepseekgui.sidebar.chatsOrder'
export const PROJECT_ORDER_STORAGE_KEY = 'deepseekgui.sidebar.projectOrder'
export const PROJECT_THREAD_ORDERS_STORAGE_KEY = 'deepseekgui.sidebar.projectThreadOrders'

function readStringArray(raw: string | null): string[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
  } catch {
    return []
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* private window / quota */
  }
}

/**
 * Apply a saved manual order to the current id list.
 * Known ids follow `manual`; unknown (new) ids keep their relative `current`
 * order and append after the manual prefix.
 */
export function applyManualOrder(current: string[], manual: string[] | null | undefined): string[] {
  if (!manual || manual.length === 0) return [...current]
  const currentSet = new Set(current)
  const seen = new Set<string>()
  const ordered: string[] = []
  for (const id of manual) {
    if (!currentSet.has(id) || seen.has(id)) continue
    ordered.push(id)
    seen.add(id)
  }
  for (const id of current) {
    if (seen.has(id)) continue
    ordered.push(id)
    seen.add(id)
  }
  return ordered
}

/** Reorder `ids` so `activeId` moves to the index of `overId`. */
export function moveIdBefore(ids: string[], activeId: string, overId: string): string[] {
  if (activeId === overId) return [...ids]
  const from = ids.indexOf(activeId)
  const to = ids.indexOf(overId)
  if (from < 0 || to < 0) return [...ids]
  const next = [...ids]
  const [item] = next.splice(from, 1)
  next.splice(to, 0, item)
  return next
}

export function loadChatsOrder(): string[] {
  try {
    return readStringArray(window.localStorage.getItem(CHATS_ORDER_STORAGE_KEY))
  } catch {
    return []
  }
}

export function persistChatsOrder(ids: string[]): void {
  writeJson(CHATS_ORDER_STORAGE_KEY, ids)
}

export function loadProjectOrder(): string[] {
  try {
    return readStringArray(window.localStorage.getItem(PROJECT_ORDER_STORAGE_KEY))
  } catch {
    return []
  }
}

export function persistProjectOrder(ids: string[]): void {
  if (ids.length === 0) {
    try {
      window.localStorage.removeItem(PROJECT_ORDER_STORAGE_KEY)
    } catch {
      /* ignore */
    }
    return
  }
  writeJson(PROJECT_ORDER_STORAGE_KEY, ids)
}

export function hasManualProjectOrder(): boolean {
  return loadProjectOrder().length > 0
}

export function loadProjectThreadOrders(): Record<string, string[]> {
  try {
    const raw = window.localStorage.getItem(PROJECT_THREAD_ORDERS_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object') return {}
    const next: Record<string, string[]> = {}
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof key !== 'string' || !key.trim()) continue
      if (!Array.isArray(value)) continue
      const ids = value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
      if (ids.length > 0) next[key] = ids
    }
    return next
  } catch {
    return {}
  }
}

export function persistProjectThreadOrders(orders: Record<string, string[]>): void {
  writeJson(PROJECT_THREAD_ORDERS_STORAGE_KEY, orders)
}

export function persistProjectThreadOrder(workspacePath: string, ids: string[]): void {
  const path = workspacePath.trim()
  if (!path) return
  const current = loadProjectThreadOrders()
  if (ids.length === 0) {
    delete current[path]
  } else {
    current[path] = ids
  }
  persistProjectThreadOrders(current)
}

export function loadProjectThreadOrder(workspacePath: string): string[] {
  const path = workspacePath.trim()
  if (!path) return []
  return loadProjectThreadOrders()[path] ?? []
}
