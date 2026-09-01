import { describe, expect, it } from 'vitest'
import { resolveInspectorSelectionUpdate } from './change-inspector-selection'

describe('resolveInspectorSelectionUpdate', () => {
  it('does not clear a shared selection while the IDE diff is mounting', () => {
    expect(
      resolveInspectorSelectionUpdate({
        fileIds: [],
        selectedId: 'git:branch:file.ts',
        loading: true,
        passive: true
      })
    ).toBeUndefined()
  })

  it('does not fight the file list when a passive diff has stale data', () => {
    expect(
      resolveInspectorSelectionUpdate({
        fileIds: ['git:branch:other.ts'],
        selectedId: 'git:branch:file.ts',
        loading: false,
        passive: true
      })
    ).toBeUndefined()
  })

  it('lets a loaded diff initialize selection when no list owns one', () => {
    expect(
      resolveInspectorSelectionUpdate({
        fileIds: ['first', 'last'],
        selectedId: null,
        loading: false,
        passive: true
      })
    ).toBe('last')
  })

  it('lets the file list replace an invalid selection', () => {
    expect(
      resolveInspectorSelectionUpdate({
        fileIds: ['first', 'last'],
        selectedId: 'missing',
        loading: false,
        passive: false
      })
    ).toBe('last')
  })
})
