// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'

vi.mock('../../i18n', () => ({ default: { t: (key: string) => key } }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../../store/chat-store', () => ({
  useChatStore: (selector: (state: object) => unknown) => selector({
    sidebarLabelColors: {}, activeThreadId: null,
    renameThread: vi.fn(), markThreadUnread: vi.fn(), setSidebarLabelColor: vi.fn()
  })
}))
vi.mock('../../hooks/use-preferred-editor-label', () => ({ usePreferredEditorLabel: () => 'Editor' }))
import { ThreadRow } from './SidebarProjectsSection'
import type { ComponentProps } from 'react'

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })

afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })

it('shows the original bubble and time with direct hover actions', async () => {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const props = {
    thread: { id: 'thread', title: '中文 Project', model: 'test', mode: 'chat', updatedAt: new Date().toISOString() },
    variant: 'project', active: false, deleting: false, showRunning: false,
    showUnread: false, hasBackgroundTask: false, pinned: false,
    onSelect: vi.fn(), onOpenTerminal: vi.fn(), onDelete: vi.fn(), onArchive: vi.fn(), onTogglePin: vi.fn()
  } satisfies ComponentProps<typeof ThreadRow>
  await act(async () => root.render(createElement(ThreadRow, props)))
  expect(container.querySelector('.lucide-message-square')).not.toBeNull()
  const meta = container.querySelector('.ds-sidebar-thread-meta')!
  expect(meta.classList.contains('group-hover:hidden')).toBe(true)
  expect(container.querySelector('[aria-label="sidebarThreadOptions"]')).toBeNull()
  for (const [label, callback] of [
    ['sidebarPinThread', props.onTogglePin], ['sidebarThreadArchive', props.onArchive]
  ] as const) {
    const button = container.querySelector<HTMLButtonElement>(`[aria-label="${label}"]`)!
    expect(button.parentElement?.classList.contains('hidden')).toBe(true)
    expect(button.parentElement?.classList.contains('group-hover:flex')).toBe(true)
    await act(async () => button.click())
    expect(callback).toHaveBeenCalledTimes(1)
  }
  expect(container.querySelector('[aria-label="sidebarThreadDelete"]')).toBeNull()
  await act(async () => container.firstElementChild!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true })))
  const deleteItem = [...document.body.querySelectorAll('button')].find(button => button.textContent?.includes('sidebarThreadDelete'))!
  expect(deleteItem).toBeDefined()
  await act(async () => deleteItem.click())
  expect(props.onDelete).toHaveBeenCalledTimes(1)
  expect(props.onSelect).not.toHaveBeenCalled()
  await act(async () => root.unmount())
})
