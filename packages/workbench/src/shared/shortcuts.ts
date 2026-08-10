/**
 * App-level keyboard shortcuts (Settings → Shortcuts).
 *
 * v1: fixed chords + per-shortcut enable toggle. Remapping comes later.
 */

export const SHORTCUT_IDS = [
  'newConversation',
  'searchConversations',
  'openKanban',
  'importProject',
  'toggleLeftSidebar',
  'toggleRightPanel',
  'saveFile',
  'approvalPolicyMenu',
  'openTerminal'
] as const

export type ShortcutId = (typeof SHORTCUT_IDS)[number]

/** Chord tokens: always require Mod (⌘/Ctrl); optional Shift; one key.
 *  Use `space` for the space bar (KeyboardEvent.key is `" "`). */
export type ShortcutChord = {
  key: string
  shift?: boolean
}

export type ShortcutDefinition = {
  id: ShortcutId
  chord: ShortcutChord
  /** When true, ignore the shortcut while focus is in an editable field. */
  ignoreWhenTyping: boolean
}

export type ShortcutPreferenceV1 = {
  enabled: boolean
}

export type ShortcutsSettingsV1 = Record<ShortcutId, ShortcutPreferenceV1>
export type ShortcutsPatchV1 = Partial<Record<ShortcutId, Partial<ShortcutPreferenceV1>>>

export const SHORTCUT_CATALOG: readonly ShortcutDefinition[] = [
  { id: 'newConversation', chord: { key: 'n' }, ignoreWhenTyping: false },
  { id: 'searchConversations', chord: { key: 'k' }, ignoreWhenTyping: false },
  { id: 'openKanban', chord: { key: 'j' }, ignoreWhenTyping: false },
  { id: 'importProject', chord: { key: 'p' }, ignoreWhenTyping: false },
  { id: 'toggleLeftSidebar', chord: { key: 'b' }, ignoreWhenTyping: true },
  { id: 'toggleRightPanel', chord: { key: 'b', shift: true }, ignoreWhenTyping: true },
  { id: 'saveFile', chord: { key: 's' }, ignoreWhenTyping: false },
  { id: 'approvalPolicyMenu', chord: { key: 'q' }, ignoreWhenTyping: false },
  { id: 'openTerminal', chord: { key: 'w' }, ignoreWhenTyping: false }
] as const

export function defaultShortcutsSettings(): ShortcutsSettingsV1 {
  const out = {} as ShortcutsSettingsV1
  for (const id of SHORTCUT_IDS) {
    out[id] = { enabled: true }
  }
  return out
}

export function normalizeShortcutsSettings(raw: unknown): ShortcutsSettingsV1 {
  const defaults = defaultShortcutsSettings()
  if (!raw || typeof raw !== 'object') return defaults
  const source = raw as Record<string, unknown>
  const out = { ...defaults }
  for (const id of SHORTCUT_IDS) {
    const entry = source[id]
    if (!entry || typeof entry !== 'object') continue
    const enabled = (entry as { enabled?: unknown }).enabled
    if (typeof enabled === 'boolean') {
      out[id] = { enabled }
    }
  }
  return out
}

export function mergeShortcutsSettings(
  current: ShortcutsSettingsV1,
  patch?: ShortcutsPatchV1 | null
): ShortcutsSettingsV1 {
  if (!patch) return normalizeShortcutsSettings(current)
  const next = { ...normalizeShortcutsSettings(current) }
  for (const id of SHORTCUT_IDS) {
    const piece = patch[id]
    if (!piece) continue
    if (typeof piece.enabled === 'boolean') {
      next[id] = { enabled: piece.enabled }
    }
  }
  return next
}

export function isShortcutEnabled(
  settings: ShortcutsSettingsV1 | null | undefined,
  id: ShortcutId
): boolean {
  if (!settings) return true
  return settings[id]?.enabled !== false
}

function normalizeShortcutKey(raw: string): string {
  const key = raw.length === 1 ? raw.toLowerCase() : raw.toLowerCase()
  if (key === ' ' || key === 'spacebar') return 'space'
  return key
}

export function matchShortcutChord(
  event: Pick<KeyboardEvent, 'key' | 'code' | 'metaKey' | 'ctrlKey' | 'altKey' | 'shiftKey'>,
  chord: ShortcutChord
): boolean {
  if (!(event.metaKey || event.ctrlKey)) return false
  if (event.altKey) return false
  if (Boolean(chord.shift) !== event.shiftKey) return false
  return normalizeShortcutKey(event.key) === normalizeShortcutKey(chord.key)
}

export function findMatchedShortcut(
  event: Pick<KeyboardEvent, 'key' | 'code' | 'metaKey' | 'ctrlKey' | 'altKey' | 'shiftKey'>
): ShortcutDefinition | null {
  for (const def of SHORTCUT_CATALOG) {
    if (matchShortcutChord(event, def.chord)) return def
  }
  return null
}

export function isEditableKeyboardTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return Boolean(target.closest('input, textarea, select, [contenteditable="true"]'))
}

function detectShortcutPlatform(): 'mac' | 'other' {
  if (typeof navigator === 'undefined') return 'other'
  return /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent)
    ? 'mac'
    : 'other'
}

/** Individual keycap tokens for Settings UI (⌘, ⇧, W) / (Ctrl, Shift, W). */
export function shortcutChordTokens(
  chord: ShortcutChord,
  platform: 'mac' | 'other' = detectShortcutPlatform()
): string[] {
  const tokens: string[] = []
  if (platform === 'mac') {
    tokens.push('⌘')
    if (chord.shift) tokens.push('⇧')
  } else {
    tokens.push('Ctrl')
    if (chord.shift) tokens.push('Shift')
  }
  const key = normalizeShortcutKey(chord.key)
  tokens.push(key === 'space' ? 'Space' : key.toUpperCase())
  return tokens
}

/** Compact string label — mac joins symbols (⌘⇧B), others use Ctrl+Shift+B. */
export function formatShortcutLabel(
  chord: ShortcutChord,
  platform: 'mac' | 'other' = detectShortcutPlatform()
): string {
  const tokens = shortcutChordTokens(chord, platform)
  return platform === 'mac' ? tokens.join('') : tokens.join('+')
}

export function shortcutDefinition(id: ShortcutId): ShortcutDefinition {
  const found = SHORTCUT_CATALOG.find((item) => item.id === id)
  if (!found) throw new Error(`Unknown shortcut id: ${id}`)
  return found
}
