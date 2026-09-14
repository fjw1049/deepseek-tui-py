// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { WorkspaceEditorPanel } from './WorkspaceEditorPanel'
import { useWorkspaceEditorStore } from '../../store/workspace-editor-store'

vi.mock('react-i18next', async (importOriginal) => ({ ...await importOriginal<typeof import('react-i18next')>(), useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../../store/chat-store', () => ({ useChatStore: (select: (state: unknown) => unknown) => select({ workspaceDirtyTick: 0 }) }))
vi.mock('../../hooks/use-git-working-changes', () => ({ useGitWorkingChanges: () => ({ result: null, reload: vi.fn() }) }))
vi.mock('./WorkspaceEditorSurface', () => ({ WorkspaceEditorSurface: () => createElement('div', null, 'file contents') }))

globalThis.IS_REACT_ACT_ENVIRONMENT = true

it('shows a persistent right tree with no files open, supports selection, toggling and resizing, and honors hideTree', async () => {
  const initial = useWorkspaceEditorStore.getState()
  const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined)
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  const previousGui = window.dsGui
  window.dsGui = {
    listWorkspaceDirectory: vi.fn(async () => ({ ok: true, entries: [{ name: 'demo.txt', path: 'demo.txt', kind: 'file' }] })),
    readWorkspaceFile: vi.fn(async () => ({ ok: true, content: 'hello', truncated: false }))
  } as unknown as typeof window.dsGui
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const click = async (selector: string) => {
    const button = host.querySelector<HTMLButtonElement>(selector)
    expect(button).toBeTruthy()
    await act(async () => button!.click())
  }
  try {
    await act(async () => root.render(createElement(WorkspaceEditorPanel, { workspaceRoot: '/workspace', blocks: [], collapsibleTree: true })))
    const copyButton = host.querySelector<HTMLButtonElement>('[aria-label="filePreviewCopyPath: /workspace"]')!
    expect(copyButton.title).toBe('/workspace')
    expect(copyButton.textContent).toContain('/workspace')
    await act(async () => copyButton.click())
    expect(writeText).toHaveBeenCalledWith('/workspace')
    expect(host.querySelector('[role="status"]')?.textContent).toBe('copySuccess')
    writeText.mockRejectedValueOnce(new Error('Clipboard unavailable'))
    await act(async () => copyButton.click())
    expect(host.querySelector('[role="status"]')?.textContent).toBe('copyFailed')
    const tree = host.querySelector('.ds-workspace-file-tree')!
    expect(tree).toBeTruthy()
    expect(tree.parentElement!.classList.contains('order-last')).toBe(true)
    expect(tree.parentElement!.classList.contains('absolute')).toBe(false)
    expect(host.textContent).toContain('workspaceEditorOpenFile')
    expect(host.textContent).not.toContain('workspaceEditorEmpty')
    const width = parseFloat(tree.parentElement!.style.width)
    await act(async () => host.querySelector('[role="separator"]')!.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0, clientX: 300 })))
    await act(async () => window.dispatchEvent(new PointerEvent('pointermove', { clientX: 280 })))
    await act(async () => window.dispatchEvent(new PointerEvent('pointerup')))
    expect(parseFloat(tree.parentElement!.style.width)).toBe(width + 20)
    await click('.ds-workspace-file-tree__row')
    expect(useWorkspaceEditorStore.getState().activeTabId).toBe('demo.txt')
    expect(host.querySelector('.ds-workspace-file-tree')).toBe(tree)
    await act(async () => useWorkspaceEditorStore.getState().closeTab('demo.txt'))
    expect(host.textContent).toContain('workspaceEditorOpenFile')
    expect(host.querySelector('.ds-workspace-file-tree')).toBe(tree)
    const toggle = host.querySelector<HTMLButtonElement>('[aria-label="workspaceEditorHideFiles"]')!
    expect(toggle.textContent).toBe('')
    expect(toggle.querySelector('.lucide-folder-open')).toBeTruthy()
    await click('[aria-expanded="true"]')
    expect(host.querySelector('.ds-workspace-file-tree')).toBeNull()
    expect(toggle.getAttribute('aria-label')).toBe('workspaceEditorBrowseFiles')
    expect(toggle.querySelector('.lucide-folder')).toBeTruthy()
    expect(toggle.textContent).toBe('')
    await click('[aria-expanded="false"]')
    expect(host.querySelector('.ds-workspace-file-tree')).toBeTruthy()
    await act(async () => root.render(createElement(WorkspaceEditorPanel, { workspaceRoot: '/workspace', blocks: [], hideTree: true })))
    expect(host.querySelector('.ds-workspace-file-tree')).toBeNull()
  } finally {
    await act(async () => root.unmount())
    useWorkspaceEditorStore.setState(initial, true)
    host.remove()
    window.localStorage?.clear()
    writeText.mockRestore()
    vi.unstubAllGlobals()
    window.dsGui = previousGui
  }
})
