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
    expect(state.tabs[0]?.revealNonce).toBe(1)
    expect(state.activeTabId).toBe('src/foo.ts')
  })

  it('bumps revealNonce when re-opening the same line', async () => {
    const { openFile } = useWorkspaceEditorStore.getState()
    await openFile('src/foo.ts', '/workspace', 9)
    expect(useWorkspaceEditorStore.getState().tabs[0]?.revealNonce).toBe(1)
    await openFile('src/foo.ts', '/workspace', 9)
    expect(useWorkspaceEditorStore.getState().tabs[0]?.revealNonce).toBe(2)
  })

  it('keeps the previous line when re-opening without one', async () => {
    const { openFile } = useWorkspaceEditorStore.getState()
    await openFile('src/foo.ts', '/workspace', 7)
    await openFile('src/foo.ts', '/workspace')
    expect(useWorkspaceEditorStore.getState().tabs[0]?.line).toBe(7)
  })

  it('keeps multiple files open as separate tabs', async () => {
    const { openFile } = useWorkspaceEditorStore.getState()
    await openFile('src/a.ts', '/workspace')
    await openFile('src/b.ts', '/workspace')
    expect(useWorkspaceEditorStore.getState().tabs.map((tab) => tab.id)).toEqual([
      'src/a.ts',
      'src/b.ts'
    ])
  })
})

describe('truncated files and revert', () => {
  const initialState = useWorkspaceEditorStore.getState()

  beforeEach(() => {
    useWorkspaceEditorStore.setState(initialState, true)
    vi.stubGlobal('window', {
      dsGui: {
        readWorkspaceFile: vi.fn(async () => ({
          ok: true,
          content: 'partial',
          truncated: true
        })),
        writeWorkspaceFile: vi.fn(async () => ({ ok: true, path: 'src/big.ts' }))
      }
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('marks truncated files and refuses to save them', async () => {
    const store = useWorkspaceEditorStore.getState()
    await store.openFile('src/big.ts', '/workspace')
    const tab = useWorkspaceEditorStore.getState().tabs[0]
    expect(tab?.truncated).toBe(true)
    useWorkspaceEditorStore.getState().updateTabContent(tab!.id, 'partial\nmore')
    const saved = await useWorkspaceEditorStore.getState().saveTab(tab!.id, '/workspace')
    expect(saved).toBe(false)
    expect(window.dsGui.writeWorkspaceFile).not.toHaveBeenCalled()
  })

  it('reverts unsaved edits back to the last saved buffer', async () => {
    vi.stubGlobal('window', {
      dsGui: {
        readWorkspaceFile: vi.fn(async () => ({
          ok: true,
          content: 'hello',
          truncated: false
        }))
      }
    })
    const { openFile, updateTabContent, revertTab } = useWorkspaceEditorStore.getState()
    await openFile('src/foo.ts', '/workspace')
    updateTabContent('src/foo.ts', 'hello world')
    expect(useWorkspaceEditorStore.getState().tabs[0]?.content).toBe('hello world')
    revertTab('src/foo.ts')
    expect(useWorkspaceEditorStore.getState().tabs[0]?.content).toBe('hello')
    expect(useWorkspaceEditorStore.getState().tabs[0]?.savedContent).toBe('hello')
  })
})

describe('editor split panes', () => {
  const initialState = useWorkspaceEditorStore.getState()

  beforeEach(() => {
    useWorkspaceEditorStore.setState(initialState, true)
    vi.stubGlobal('window', {
      dsGui: {
        readWorkspaceFile: vi.fn(async () => ({
          ok: true,
          content: 'ok',
          truncated: false
        }))
      }
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('keeps a file open in the other pane when the left copy is closed', async () => {
    const { openFile, closeTab } = useWorkspaceEditorStore.getState()
    await openFile('src/a.ts', '/workspace')
    await openFile('src/a.ts', '/workspace', undefined, undefined, { toSide: true })

    const split = useWorkspaceEditorStore.getState()
    expect(split.splitEnabled).toBe(true)
    expect(split.primaryTabIds).toEqual(['src/a.ts'])
    expect(split.secondaryTabIds).toEqual(['src/a.ts'])

    closeTab('src/a.ts', 'primary')
    const after = useWorkspaceEditorStore.getState()
    expect(after.splitEnabled).toBe(false)
    expect(after.tabs.map((tab) => tab.id)).toEqual(['src/a.ts'])
    expect(after.primaryTabIds).toEqual(['src/a.ts'])
    expect(after.activeTabId).toBe('src/a.ts')
    expect(after.secondaryTabId).toBeNull()
    expect(after.secondaryTabIds).toEqual([])
  })

  it('keeps the left pane when the right copy is closed', async () => {
    const { openFile, closeTab } = useWorkspaceEditorStore.getState()
    await openFile('src/a.ts', '/workspace')
    await openFile('src/a.ts', '/workspace', undefined, undefined, { toSide: true })

    closeTab('src/a.ts', 'secondary')
    const after = useWorkspaceEditorStore.getState()
    expect(after.splitEnabled).toBe(false)
    expect(after.tabs.map((tab) => tab.id)).toEqual(['src/a.ts'])
    expect(after.primaryTabIds).toEqual(['src/a.ts'])
    expect(after.activeTabId).toBe('src/a.ts')
  })

  it('opens a different file to the side without dropping the left tab', async () => {
    const { openFile, closeTab } = useWorkspaceEditorStore.getState()
    await openFile('src/a.ts', '/workspace')
    await openFile('src/b.ts', '/workspace', undefined, undefined, { toSide: true })

    const split = useWorkspaceEditorStore.getState()
    expect(split.splitEnabled).toBe(true)
    expect(split.primaryTabIds).toEqual(['src/a.ts'])
    expect(split.secondaryTabIds).toEqual(['src/b.ts'])
    expect(split.activeTabId).toBe('src/a.ts')
    expect(split.secondaryTabId).toBe('src/b.ts')

    closeTab('src/a.ts', 'primary')
    const after = useWorkspaceEditorStore.getState()
    expect(after.splitEnabled).toBe(false)
    expect(after.tabs.map((tab) => tab.id)).toEqual(['src/b.ts'])
    expect(after.primaryTabIds).toEqual(['src/b.ts'])
    expect(after.activeTabId).toBe('src/b.ts')
  })

  it('merges both panes into the primary strip when closing the split', async () => {
    const { openFile, closeSplit } = useWorkspaceEditorStore.getState()
    await openFile('src/a.ts', '/workspace')
    await openFile('src/b.ts', '/workspace', undefined, undefined, { toSide: true })

    closeSplit()
    const after = useWorkspaceEditorStore.getState()
    expect(after.splitEnabled).toBe(false)
    expect(after.primaryTabIds).toEqual(['src/a.ts', 'src/b.ts'])
    expect(after.secondaryTabIds).toEqual([])
    expect(after.tabs).toHaveLength(2)
    expect(after.activeTabId).toBe('src/b.ts')
  })

  it('closing a tab in one pane leaves the other pane open', async () => {
    const { openFile, closeTab } = useWorkspaceEditorStore.getState()
    await openFile('src/a.ts', '/workspace')
    await openFile('src/b.ts', '/workspace')
    await openFile('src/b.ts', '/workspace', undefined, undefined, { toSide: true })

    closeTab('src/b.ts', 'primary')
    const after = useWorkspaceEditorStore.getState()
    expect(after.splitEnabled).toBe(true)
    expect(after.primaryTabIds).toEqual(['src/a.ts'])
    expect(after.secondaryTabIds).toEqual(['src/b.ts'])
    expect(after.activeTabId).toBe('src/a.ts')
    expect(after.secondaryTabId).toBe('src/b.ts')
    expect(after.tabs.map((tab) => tab.id)).toEqual(['src/a.ts', 'src/b.ts'])
  })
})
