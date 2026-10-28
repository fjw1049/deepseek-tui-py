// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { WorkspaceEditorSurface } from './WorkspaceEditorSurface'
import type { EditorTab } from '../../store/workspace-editor-store'
import type { editor as MonacoEditor, IScrollEvent } from 'monaco-editor'
const state = vi.hoisted(() => ({ pending: new Map<string, Promise<void>>(), options: {} as Record<string, unknown>, mount: undefined as ((editor: MonacoEditor.IStandaloneCodeEditor) => void) | undefined }))
vi.mock('../../lib/monaco-editor-setup', () => ({
  ensureMonacoConfigured() {}, ensureWorkspaceMonacoThemes() {},
  workspaceMonacoTheme: () => 'ds-workspace-light',
  isWorkspaceLanguageReady: (language: string) => language === 'plaintext',
  prepareWorkspaceLanguage: (language: string) => state.pending.get(language) ?? Promise.resolve()
}))
vi.mock('../../lib/workspace-monaco-models', () => ({ workspaceModelPath: (id: string) => id, prepareWorkspaceModel() {}, pruneClosedWorkspaceModels() {} }))
vi.mock('../../lib/apply-editor-diff-highlights', () => ({ applyEditorDiffHighlights: () => () => {} }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('@monaco-editor/react', () => ({ default: (props: {path: string; defaultValue: string; options: Record<string, unknown>; onMount: typeof state.mount}) => {
  state.options = props.options
  state.mount = props.onMount
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

it('reports virtual position changes, ignores size-only notifications, and disposes the listener', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  const host = document.createElement('div')
  const root = createRoot(host)
  const activity = vi.fn()
  host.addEventListener('ds-editor-scroll', activity)
  let scroll: ((event: IScrollEvent) => void) | undefined
  const dispose = vi.fn(() => { scroll = undefined })
  const layout = vi.fn()
  const editor = {
    updateOptions() {}, layout, getModel: () => null,
    onDidChangeCursorSelection: () => ({ dispose() {} }),
    onDidScrollChange: (callback: typeof scroll) => { scroll = callback; return { dispose } }
  } as unknown as MonacoEditor.IStandaloneCodeEditor
  try {
    await act(async () => root.render(createElement(WorkspaceEditorSurface, { paneId: 'primary', tab: tab('a.ts'), readOnly: true, onChange() {} })))
    await act(async () => state.mount!(editor))
    const initialLayouts = layout.mock.calls.length
    await act(async () => scroll!({ scrollTopChanged: false, scrollLeftChanged: false } as IScrollEvent))
    expect(activity).not.toHaveBeenCalled()
    await act(async () => scroll!({ scrollTopChanged: true, scrollLeftChanged: false } as IScrollEvent))
    await act(async () => scroll!({ scrollTopChanged: false, scrollLeftChanged: true } as IScrollEvent))
    expect(activity).toHaveBeenCalledTimes(2)
    expect(layout).toHaveBeenCalledTimes(initialLayouts)
    await act(async () => root.unmount())
    expect(dispose).toHaveBeenCalledOnce()
    expect(scroll).toBeUndefined()
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

it('defers maximized editor layout only while the left rail animates and cancels pending work on unmount', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  let resize = () => {}
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { resize = callback }
    observe() {} disconnect() {}
  })
  const frames = new Map<number, FrameRequestCallback>()
  let id = 0
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { frames.set(++id, callback); return id })
  vi.stubGlobal('cancelAnimationFrame', (key: number) => frames.delete(key))
  const flush = () => { const callbacks = [...frames.values()]; frames.clear(); callbacks.forEach(callback => callback(0)) }
  const shell = document.createElement('div')
  shell.className = 'ds-workbench-shell'
  shell.innerHTML = '<div class="ds-workbench-sidebar-wrap"></div><div class="ds-workbench-right-panel" data-fill-width><div></div></div>'
  document.body.append(shell)
  const rail = shell.firstElementChild!
  let running = false
  Object.defineProperty(rail, 'getAnimations', { value: () => running ? [{ transitionProperty: 'width', playState: 'running' }] : [] })
  const panel = shell.lastElementChild!
  const root = createRoot(panel.firstElementChild!)
  const layout = vi.fn()
  const editor = {
    layout, updateOptions() {}, getModel: () => null,
    onDidChangeCursorSelection: () => ({ dispose() {} }),
    onDidScrollChange: () => ({ dispose() {} })
  } as unknown as MonacoEditor.IStandaloneCodeEditor
  try {
    await act(async () => root.render(createElement(WorkspaceEditorSurface, { paneId: 'primary', tab: tab('a.txt'), readOnly: false, onChange() {} })))
    await act(async () => state.mount!(editor))
    flush(); layout.mockClear()
    running = true
    resize(); resize(); flush()
    expect(layout).not.toHaveBeenCalled()
    expect(frames.size).toBe(1)
    running = false
    flush()
    expect(layout).toHaveBeenCalledTimes(1)
    resize()
    expect(layout).toHaveBeenCalledTimes(2)
    running = true
    panel.removeAttribute('data-fill-width')
    resize()
    expect(layout).toHaveBeenCalledTimes(3)
    panel.setAttribute('data-fill-width', '')
    resize()
    expect(frames.size).toBe(1)
  } finally { await act(async () => root.unmount()); shell.remove() }
  expect(frames.size).toBe(0)
})
