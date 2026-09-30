// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { IdeWorkspaceLayout } from './IdeWorkspaceLayout'

vi.mock('react-i18next', async (importOriginal) => ({ ...await importOriginal<typeof import('react-i18next')>(), useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../../hooks/use-git-working-changes', () => {
  const reload = vi.fn(async () => {})
  return {
    useGitBranchCompareBase: () => [undefined, reload],
    useGitWorkingChanges: () => ({ result: null, loading: false, reload })
  }
})
vi.mock('../../hooks/use-git-branches', () => {
  const reload = vi.fn(async () => {})
  return { useGitBranches: () => ({ result: null, loading: false, reload }) }
})
vi.mock('../../store/chat-store', () => ({
  useChatStore: (select: (state: unknown) => unknown) => select({ workspaceDirtyTick: 0, activeThreadId: null, threads: [] })
}))
vi.mock('../../store/workspace-editor-store', () => ({
  useWorkspaceEditorStore: (select: (state: unknown) => unknown) => select({ openFile: vi.fn(async () => {}), tabs: [], activeTabId: null })
}))
vi.mock('../workspace-editor/WorkspaceEditorPanel', () => ({
  WorkspaceEditorPanel: () => createElement('textarea', { 'data-editor': '', defaultValue: 'unsaved source' })
}))
vi.mock('../ChangeInspector', () => ({
  ChangeInspector: ({ variant, active }: { variant: string; active?: boolean }) => createElement('div', { 'data-inspector': variant, 'data-active': String(active) }, variant)
}))

it('keeps file, change and chat contents when switching activities and toggling panes', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const storage = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => { storage.set(key, value) },
    removeItem: (key: string) => { storage.delete(key) }
  })
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const click = async (activity: string) => {
    await act(async () => host.querySelector<HTMLButtonElement>(`[aria-label="${activity}"]`)!.click())
  }
  try {
    await act(async () => root.render(createElement(IdeWorkspaceLayout, {
      workspaceRoot: '/workspace', blocks: [],
      chatRail: createElement('textarea', { 'data-chat': '', defaultValue: 'chat draft' }),
      onExitIdeMode: vi.fn(), onOpenFileInEditor: vi.fn()
    })))
    const editor = host.querySelector<HTMLTextAreaElement>('[data-editor]')!
    expect(host.querySelector('[data-inspector]')).toBeNull()
    await click('ideActivityChanges')
    const list = host.querySelector('[data-inspector="list"]')!
    const diff = host.querySelector('[data-inspector="diff"]')!
    const listPane = list.closest<HTMLElement>('.ds-ide-changes-list')!
    const diffPane = diff.closest<HTMLElement>('.ds-ide-changes-stage')!
    diff.scrollTop = 170
    await click('ideActivityFiles')
    expect(host.querySelector('[data-editor]')).toBe(editor)
    expect(editor.value).toBe('unsaved source')
    expect(host.querySelector('[data-inspector="list"]')).toBe(list)
    expect(host.querySelector('[data-inspector="diff"]')).toBe(diff)
    expect(listPane.style.display).toBe('none')
    expect(list.getAttribute('data-active')).toBe('false')
    expect(diffPane.hasAttribute('inert')).toBe(true)
    await click('ideActivityChanges')
    expect(listPane.style.display).toBe('flex')
    expect(list.getAttribute('data-active')).toBe('true')
    expect(diffPane.hasAttribute('inert')).toBe(false)
    expect(diff.scrollTop).toBe(170)
    await click('ideActivityChanges')
    expect(listPane.style.display).toBe('none')
    expect(diffPane.style.display).toBe('flex')
    expect(host.querySelector('[data-inspector="list"]')).toBe(list)
    const chat = host.querySelector<HTMLTextAreaElement>('[data-chat]')!
    const rail = host.querySelector<HTMLElement>('.ds-ide-chat-rail')!
    await act(async () => host.querySelector<HTMLButtonElement>('[title="ideChatRailHide"]')!.click())
    expect(rail.style.width).toBe('0px')
    expect(rail.hasAttribute('inert')).toBe(true)
    expect(host.querySelector('[data-chat]')).toBe(chat)
    await act(async () => host.querySelector<HTMLButtonElement>('[title="ideChatRailShow"]')!.click())
    expect(parseFloat(rail.style.width)).toBeGreaterThan(0)
    expect(rail.hasAttribute('inert')).toBe(false)
    expect(host.querySelector('[data-chat]')).toBe(chat)
    expect(chat.value).toBe('chat draft')
    expect(host.querySelector('[data-editor]')).toBe(editor)
    expect(host.querySelector('[data-inspector="diff"]')).toBe(diff)
  } finally {
    await act(async () => root.unmount())
    host.remove()
    vi.unstubAllGlobals()
  }
})
