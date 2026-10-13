import { describe, expect, it, vi } from 'vitest'
import { Uri, editor } from 'monaco-editor'
import { workspaceModelPath, prepareWorkspaceModel } from './workspace-monaco-models'

vi.mock('monaco-editor', async () => {
  // Exercise Monaco's actual URI validation without loading its browser editor.
  // @ts-expect-error Monaco does not publish declarations for this internal module.
  const { URI } = await import('monaco-editor/esm/vs/base/common/uri.js')
  return { Uri: URI, editor: { getModel: vi.fn(), createModel: vi.fn(), colorizeModelLine: vi.fn() } }
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


it('prepares a bounded first viewport once and preserves existing models', () => {
  const tab = { id: 'a.py', path: 'a.py', kind: 'text' as const, content: 'example', savedContent: 'example', loading: false, error: null }
  const model = { getLineCount: () => 2000 } as unknown as editor.ITextModel
  vi.mocked(editor.createModel).mockReturnValue(model)
  prepareWorkspaceModel(tab, 'primary')
  expect(editor.createModel).toHaveBeenCalledWith('example', 'python', Uri.parse(workspaceModelPath(tab.id, 'primary')))
  expect(editor.colorizeModelLine).toHaveBeenCalledWith(model, 200)
  vi.mocked(editor.getModel).mockReturnValue(model)
  prepareWorkspaceModel({ ...tab, content: 'do not overwrite edits' }, 'primary')
  expect(editor.createModel).toHaveBeenCalledTimes(1)
  expect(editor.colorizeModelLine).toHaveBeenCalledTimes(1)
})
