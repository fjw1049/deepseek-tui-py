import type { AppSettingsV1 } from '@shared/app-settings'

// Renderer-memory only. A replaced bridge (including a new test session) gets a fresh cache.
const snapshots = new WeakMap<object, { settings: AppSettingsV1; revision: number }>()

export function getSettingsSnapshot(): AppSettingsV1 | null {
  return window.dsGui ? snapshots.get(window.dsGui)?.settings ?? null : null
}

export function cacheSettingsSnapshot(settings: AppSettingsV1): void {
  const bridge = window.dsGui
  if (bridge) snapshots.set(bridge, { settings, revision: (snapshots.get(bridge)?.revision ?? 0) + 1 })
}

export async function loadSettingsSnapshot(): Promise<AppSettingsV1> {
  const bridge = window.dsGui
  const revision = snapshots.get(bridge)?.revision ?? 0
  const settings = await bridge.getSettings()
  const current = snapshots.get(bridge)
  // A read started before a successful save must not replace the saved snapshot.
  if (current && current.revision !== revision) return current.settings
  snapshots.set(bridge, { settings, revision: revision + 1 })
  return settings
}
