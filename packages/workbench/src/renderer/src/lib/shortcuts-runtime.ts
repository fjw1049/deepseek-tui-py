import {
  defaultShortcutsSettings,
  isShortcutEnabled as readEnabled,
  normalizeShortcutsSettings,
  type ShortcutId,
  type ShortcutsSettingsV1
} from '@shared/shortcuts'

export const OPEN_SIDEBAR_SEARCH_EVENT = 'deepseekgui:open-sidebar-search'
export const OPEN_APPROVAL_POLICY_EVENT = 'deepseekgui:open-approval-policy'

let current: ShortcutsSettingsV1 = defaultShortcutsSettings()
const listeners = new Set<() => void>()

export function applyShortcutsSettings(raw: unknown): ShortcutsSettingsV1 {
  current = normalizeShortcutsSettings(raw)
  for (const listener of listeners) listener()
  return current
}

export function getShortcutsSettings(): ShortcutsSettingsV1 {
  return current
}

export function isShortcutEnabled(id: ShortcutId): boolean {
  return readEnabled(current, id)
}

export function subscribeShortcuts(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function requestOpenSidebarSearch(): void {
  window.dispatchEvent(new CustomEvent(OPEN_SIDEBAR_SEARCH_EVENT))
}

export function requestOpenApprovalPolicyMenu(): void {
  window.dispatchEvent(new CustomEvent(OPEN_APPROVAL_POLICY_EVENT))
}
