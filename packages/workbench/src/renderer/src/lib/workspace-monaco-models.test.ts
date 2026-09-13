import { describe, expect, it, vi } from 'vitest'
import { Uri } from 'monaco-editor'
import { workspaceModelPath } from './workspace-monaco-models'

vi.mock('monaco-editor', async () => {
  // Exercise Monaco's actual URI validation without loading its browser editor.
  // @ts-expect-error Monaco does not publish declarations for this internal module.
  const { URI } = await import('monaco-editor/esm/vs/base/common/uri.js')
  return { Uri: URI }
})
vi.mock('../store/workspace-editor-store', () => ({
  useWorkspaceEditorStore: { subscribe: vi.fn(() => vi.fn()) }
}))

describe('workspaceModelPath', () => {
  it.each([
    'src/main.ts',
    '/Users/fjw/project/main.ts',
    'C:/project/main.ts',
    'src/中文 file #1?100%.ts',
    '//server/share/main.ts'
  ])('round-trips the tab ID %s through a valid model URI', (tabId) => {
    const uri = Uri.parse(workspaceModelPath(tabId, 'primary'))
    expect(uri.scheme).toBe('workspace')
    expect(uri.authority).toBe('primary')
    expect(uri.path).toBe(`/tabs/${tabId}`)
    expect(uri.query).toBe('')
    expect(uri.fragment).toBe('')
  })

  it('keeps model identities stable and distinct across panes and tab IDs', () => {
    const ids = ['src/main.ts', '/src/main.ts', 'src/main%20file.ts', 'src/main file.ts']
    const paths = ids.flatMap((id) => [workspaceModelPath(id, 'primary'), workspaceModelPath(id, 'secondary')])
    expect(new Set(paths).size).toBe(paths.length)
    expect(workspaceModelPath(ids[0], 'primary')).toBe(paths[0])
  })
})
