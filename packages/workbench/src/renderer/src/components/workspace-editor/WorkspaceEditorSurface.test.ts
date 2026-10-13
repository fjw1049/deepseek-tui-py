// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { WorkspaceEditorSurface } from './WorkspaceEditorSurface'
import type { EditorTab } from '../../store/workspace-editor-store'
const state = vi.hoisted(() => ({ pending: new Map<string, Promise<void>>(), options: {} as Record<string, unknown> }))
vi.mock('../../lib/monaco-editor-setup', () => ({
  ensureMonacoConfigured() {}, ensureWorkspaceMonacoThemes() {},
  workspaceMonacoTheme: () => 'ds-workspace-light',
  isWorkspaceLanguageReady: (language: string) => language === 'plaintext',
  prepareWorkspaceLanguage: (language: string) => state.pending.get(language) ?? Promise.resolve()
}))
vi.mock('../../lib/workspace-monaco-models', () => ({ workspaceModelPath: (id: string) => id, prepareWorkspaceModel() {}, pruneClosedWorkspaceModels() {} }))
vi.mock('../../lib/apply-editor-diff-highlights', () => ({ applyEditorDiffHighlights: () => () => {} }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@monaco-editor/react', () => ({ default: (props: {path: string; defaultValue: string; options: Record<string, unknown>}) => {
  state.options = props.options
  return createElement('div', { 'data-editor': props.path }, props.defaultValue)
} }))
const tab = (path: string, loading = false): EditorTab => ({ id: path, path, kind: 'text', content: path + ' code', savedContent: path + ' code', loading, error: null })
afterEach(() => { state.pending.clear(); vi.unstubAllGlobals(); document.documentElement.style.removeProperty('--font-mono') })

it('keeps the editor through reads and grammar loading, ignores late results, and sets the initial font', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  document.documentElement.style.setProperty('--font-mono', 'Test Mono')
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  const draw = async (file: EditorTab) => act(async () => root.render(createElement(WorkspaceEditorSurface, { paneId: 'primary', tab: file, readOnly: false, onChange() {} })))
  try {
    await draw(tab('a.txt'))
    const editor = host.querySelector('[data-editor]')!
    expect(state.options.fontFamily).toBe('Test Mono')
    let finishPython!: () => void
    state.pending.set('python', new Promise(resolve => { finishPython = resolve }))
    await draw(tab('b.py', true))
    expect(host.querySelector('[data-editor]')).toBe(editor)
    expect(editor.textContent).toBe('a.txt code')
    expect(host.querySelector('[inert]')).not.toBeNull()
    expect(state.options.readOnly).toBe(true)
    await draw(tab('b.py'))
    expect(editor.textContent).toBe('a.txt code')
    await draw(tab('c.txt'))
    await act(async () => finishPython())
    expect(editor.textContent).toBe('c.txt code')
    expect(host.querySelector('[data-editor]')).toBe(editor)
    expect(host.querySelector('[inert]')).toBeNull()
    await draw(tab('b.py'))
    expect(editor.textContent).toBe('b.py code')
    expect(state.options.readOnly).toBe(false)
  } finally { await act(async () => root.unmount()); host.remove() }
})

it('allows reading after a grammar load failure', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  const host = document.createElement('div'); const root = createRoot(host)
  state.pending.set('python', Promise.reject(new Error('grammar unavailable')))
  try {
    await act(async () => root.render(createElement(WorkspaceEditorSurface, { paneId: 'primary', tab: tab('a.py'), readOnly: true, onChange() {} })))
    expect(host.querySelector('[data-editor]')?.textContent).toBe('a.py code')
    expect(host.querySelector('[aria-busy]')?.getAttribute('aria-busy')).toBe('false')
  } finally { await act(async () => root.unmount()); host.remove() }
})
