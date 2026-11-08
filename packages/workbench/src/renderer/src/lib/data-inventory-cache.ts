export type DataInventory = {
  home_dir: string
  threads_dir: string
  sessions_dir: string
  state_db_path: string
  threads_bytes: number
  sessions_bytes: number
  state_db_bytes: number
  events_bytes: number
  checkpoints_bytes: number
  thread_count: number
  message_count: number
  item_count: number
  total_bytes: number
  /** Whole data home, split so the parts add up (absent on runtimes before categories). */
  storage_total_bytes?: number
  categories?: Array<{ key: StorageCategory; bytes: number; reveal_path?: string | null }>
  workspace_dir?: string
  log_keep_hours?: number | null
}
export type StorageCategory = 'conversations' | 'browser' | 'workspace' | 'logs' | 'worktrees' | 'other'

type Entry = { value: DataInventory | null; updatedAt: number; pending?: Promise<DataInventory> }
// In-memory only: reopening Settings reuses the last completed scan. Different
// bridge instances cannot share data, and restarting the app starts fresh.
const entries = new WeakMap<Window['dsGui']['runtimeRequest'], Entry>()
function entry(): Entry {
  const request = window.dsGui.runtimeRequest
  let current = entries.get(request)
  if (!current) {
    current = { value: null, updatedAt: 0 }
    entries.set(request, current)
  }
  return current
}
export function getDataInventorySnapshot(): DataInventory | null {
  return typeof window === 'undefined' || !window.dsGui ? null : entry().value
}
export function loadDataInventory(force = false): Promise<DataInventory> {
  const current = entry()
  if (current.pending) {
    // Mutations require a scan started after the mutation, never an older in-flight scan.
    return force ? current.pending.catch(() => null).then(() => loadDataInventory(true)) : current.pending
  }
  if (!force && current.value && Date.now() - current.updatedAt < 30_000) return Promise.resolve(current.value)
  current.pending = window.dsGui.runtimeRequest('/v1/data/inventory', 'GET').then(response => {
    if (!response.ok) throw new Error('Inventory unavailable')
    const inventory = JSON.parse(response.body) as DataInventory
    current.value = inventory
    current.updatedAt = Date.now()
    return inventory
  }).finally(() => { current.pending = undefined })
  return current.pending
}
