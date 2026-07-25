import { describe, expect, it } from 'vitest'
import {
  defaultShortcutsSettings,
  findMatchedShortcut,
  formatShortcutLabel,
  isShortcutEnabled,
  matchShortcutChord,
  mergeShortcutsSettings,
  normalizeShortcutsSettings,
  shortcutChordTokens
} from './shortcuts'

function keyEvent(
  partial: Partial<KeyboardEvent> & Pick<KeyboardEvent, 'key'>
): Pick<KeyboardEvent, 'key' | 'code' | 'metaKey' | 'ctrlKey' | 'altKey' | 'shiftKey'> {
  return {
    key: partial.key,
    code: partial.code ?? '',
    metaKey: partial.metaKey ?? false,
    ctrlKey: partial.ctrlKey ?? false,
    altKey: partial.altKey ?? false,
    shiftKey: partial.shiftKey ?? false
  }
}

describe('shortcuts', () => {
  it('defaults every catalog id to enabled', () => {
    const defaults = defaultShortcutsSettings()
    expect(defaults.newConversation.enabled).toBe(true)
    expect(defaults.saveFile.enabled).toBe(true)
  })

  it('normalizes partial and unknown entries', () => {
    const next = normalizeShortcutsSettings({
      newConversation: { enabled: false },
      bogus: { enabled: false }
    })
    expect(next.newConversation.enabled).toBe(false)
    expect(next.searchConversations.enabled).toBe(true)
  })

  it('merges preference patches', () => {
    const base = defaultShortcutsSettings()
    const merged = mergeShortcutsSettings(base, { toggleLeftSidebar: { enabled: false } })
    expect(merged.toggleLeftSidebar.enabled).toBe(false)
    expect(merged.newConversation.enabled).toBe(true)
  })

  it('matches mod chords and shift variants', () => {
    expect(matchShortcutChord(keyEvent({ key: 'n', metaKey: true }), { key: 'n' })).toBe(true)
    expect(matchShortcutChord(keyEvent({ key: 'N', ctrlKey: true }), { key: 'n' })).toBe(true)
    expect(
      matchShortcutChord(keyEvent({ key: 'b', metaKey: true, shiftKey: true }), {
        key: 'b',
        shift: true
      })
    ).toBe(true)
    expect(matchShortcutChord(keyEvent({ key: 'b', metaKey: true }), { key: 'b', shift: true })).toBe(
      false
    )
    expect(findMatchedShortcut(keyEvent({ key: 'k', metaKey: true }))?.id).toBe(
      'searchConversations'
    )
    expect(findMatchedShortcut(keyEvent({ key: 'p', metaKey: true }))?.id).toBe('importProject')
    expect(findMatchedShortcut(keyEvent({ key: 'q', metaKey: true }))?.id).toBe(
      'approvalPolicyMenu'
    )
    expect(findMatchedShortcut(keyEvent({ key: 'w', metaKey: true }))?.id).toBe('openTerminal')
    expect(findMatchedShortcut(keyEvent({ key: 'W', ctrlKey: true }))?.id).toBe('openTerminal')
  })

  it('formats labels for mac and other platforms', () => {
    expect(shortcutChordTokens({ key: 'n' }, 'mac')).toEqual(['⌘', 'N'])
    expect(shortcutChordTokens({ key: 'b', shift: true }, 'mac')).toEqual(['⌘', '⇧', 'B'])
    expect(shortcutChordTokens({ key: 'b', shift: true }, 'other')).toEqual([
      'Ctrl',
      'Shift',
      'B'
    ])
    expect(formatShortcutLabel({ key: 'n' }, 'mac')).toBe('⌘N')
    expect(formatShortcutLabel({ key: 'b', shift: true }, 'mac')).toBe('⌘⇧B')
    expect(formatShortcutLabel({ key: 'b', shift: true }, 'other')).toBe('Ctrl+Shift+B')
    expect(formatShortcutLabel({ key: 'w' }, 'mac')).toBe('⌘W')
    expect(formatShortcutLabel({ key: 'w' }, 'other')).toBe('Ctrl+W')
    expect(formatShortcutLabel({ key: 'space' }, 'mac')).toBe('⌘Space')
    expect(formatShortcutLabel({ key: 'space' }, 'other')).toBe('Ctrl+Space')
  })

  it('treats missing settings as enabled', () => {
    expect(isShortcutEnabled(undefined, 'saveFile')).toBe(true)
    expect(
      isShortcutEnabled(
        { ...defaultShortcutsSettings(), saveFile: { enabled: false } },
        'saveFile'
      )
    ).toBe(false)
  })
})
