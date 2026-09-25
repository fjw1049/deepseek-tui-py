import { expect, it, vi } from 'vitest'
import { useWorkspaceEditorStore } from './workspace-editor-store'

it('opens PDF without decoding binary data or allowing a text save', async () => {
  const readWorkspaceFile = vi.fn()
  const writeWorkspaceFile = vi.fn()
  vi.stubGlobal('window', { dsGui: { readWorkspaceFile, writeWorkspaceFile } })
  const initial = useWorkspaceEditorStore.getState()
  try {
    expect(await initial.openFile('/workspace/report.pdf', '/workspace')).toBe(true)
    const state = useWorkspaceEditorStore.getState()
    const tab = state.tabs.find((item) => item.path === '/workspace/report.pdf')!
    expect(tab.kind).toBe('pdf')
    expect(tab.loading).toBe(false)
    expect(readWorkspaceFile).not.toHaveBeenCalled()
    expect(await state.saveTab(tab.id, '/workspace')).toBe(false)
    expect(writeWorkspaceFile).not.toHaveBeenCalled()
  } finally {
    useWorkspaceEditorStore.setState(initial, true)
    vi.unstubAllGlobals()
  }
})
