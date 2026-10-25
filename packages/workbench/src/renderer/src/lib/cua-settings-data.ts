import { readTomlBool } from '@shared/toml-section'

type InheritedCua = { enabled: boolean; chrome: boolean; autoAllowApps: boolean }
export type PrivacyEntry = { id: 'accessibility' | 'screen'; name: string; path: string }
type Snapshot<T> = { value: T | null; failed: boolean }

// Only configuration and component identities are cached, never OS permission grants.
// Shared by startup and settings; a slow request must not repeat on every navigation.
function resource<T>(read: () => Promise<T>) {
  let snapshot: Snapshot<T> = { value: null, failed: false }
  let updatedAt = 0
  let pending: Promise<void> | null = null
  const listeners = new Set<() => void>()
  const publish = (next: Snapshot<T>): void => {
    snapshot = next
    listeners.forEach(listener => listener())
  }
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } },
    load(force = false): Promise<void> {
      if (pending) return pending
      if (!force && updatedAt && Date.now() - updatedAt < 60_000) return Promise.resolve()
      publish({ ...snapshot, failed: false })
      pending = Promise.resolve().then(read).then(
        value => { updatedAt = Date.now(); publish({ value, failed: false }) },
        () => { publish({ ...snapshot, failed: true }) }
      ).finally(() => { pending = null })
      return pending
    }
  }
}

function createData(bridge: Window['dsGui']) {
  return {
    config: resource<InheritedCua>(async () => {
      const { content } = await bridge.getDeepseekConfigFile()
      return {
        enabled: readTomlBool(content ?? '', 'enabled', { section: 'cua' }) ?? false,
        chrome: readTomlBool(content ?? '', 'chrome', { section: 'cua' }) ?? false,
        autoAllowApps: readTomlBool(content ?? '', 'auto_allow_apps', { section: 'cua' }) ?? false
      }
    }),
    permissions: resource<PrivacyEntry[]>(async () => {
      const response = await bridge.runtimeRequest('/v1/cua/permissions', 'GET')
      if (!response.ok) throw new Error('Permissions unavailable')
      const value = JSON.parse(response.body) as { permissions?: PrivacyEntry[] }
      if (!Array.isArray(value.permissions)) throw new Error('Invalid permissions')
      return value.permissions
    })
  }
}
const caches = new WeakMap<object, ReturnType<typeof createData>>()
export function getCuaSettingsData(): ReturnType<typeof createData> {
  const bridge = window.dsGui
  let data = caches.get(bridge)
  if (!data) { data = createData(bridge); caches.set(bridge, data) }
  return data
}

export function preloadCuaSettings(runtimeReady: boolean): void {
  const platform = window.dsGui?.platform
  if (platform !== 'darwin' && platform !== 'linux') return
  const data = getCuaSettingsData()
  void data.config.load()
  // The API cannot respond before the runtime is ready. Recheck after reconnects.
  if (platform === 'darwin' && runtimeReady) void data.permissions.load(true)
}
