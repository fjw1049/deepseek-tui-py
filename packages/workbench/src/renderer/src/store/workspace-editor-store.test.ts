import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { normalizeEditorPathForTab, useWorkspaceEditorStore } from './workspace-editor-store'

describe('normalizeEditorPathForTab', () => {
  it('preserves absolute POSIX paths from resolved file references', () => {
    expect(normalizeEditorPathForTab('/Users/fjw/Desktop/Tanzo-main/scratch/report.md')).toBe(
      '/Users/fjw/Desktop/Tanzo-main/scratch/report.md'
    )
  })

  it('normalizes separators without converting relative paths to absolute paths', () => {
    expect(normalizeEditorPathForTab('scratch\\report.md')).toBe('scratch/report.md')
  })
})

describe('openFile line targeting', () => {
  const initialState = useWorkspaceEditorStore.getState()

  beforeEach(() => {
    useWorkspaceEditorStore.setState(initialState, true)
    vi.stubGlobal('window', {
      dsGui: {
        readWorkspaceFile: vi.fn(async () => ({
          ok: true,
          content: 'one\ntwo\nthree',
          truncated: false
        }))
      }
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('stores the requested line on first open', async () => {
    await useWorkspaceEditorStore.getState().openFile('src/foo.ts', '/workspace', 5)
    expect(useWorkspaceEditorStore.getState().tabs[0]?.line).toBe(5)
  })

  it('updates the line of an already-open tab when a new line is provided', async () => {
    const { openFile } = useWorkspaceEditorStore.getState()
    await openFile('src/foo.ts', '/workspace')
    expect(useWorkspaceEditorStore.getState().tabs[0]?.line).toBeUndefined()

    await openFile('src/foo.ts', '/workspace', 42)
    const state = useWorkspaceEditorStore.getState()
    expect(state.tabs).toHaveLength(1)
    expect(state.tabs[0]?.line).toBe(42)
    expect(state.activeTabId).toBe('src/foo.ts')
  })

  it('keeps the previous line when re-opening without one', async () => {
    const { openFile } = useWorkspaceEditorStore.getState()
    await openFile('src/foo.ts', '/workspace', 7)
    await openFile('src/foo.ts', '/workspace')
    expect(useWorkspaceEditorStore.getState().tabs[0]?.line).toBe(7)
  })
})
