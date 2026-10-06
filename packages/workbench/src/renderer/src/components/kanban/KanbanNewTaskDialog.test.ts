// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { KanbanNewTaskDialog } from './KanbanNewTaskDialog'

const { state, t } = vi.hoisted(() => ({
  state: { composerModel: 'a', composerPickList: ['a', 'b'], composerModelMeta: {} },
  t: (key: string) => key
}))
vi.mock('react-i18next', async (original) => ({ ...await original<typeof import('react-i18next')>(), useTranslation: () => ({ t }) }))
vi.mock('../../store/chat-store', () => ({ useChatStore: (select: (value: typeof state) => unknown) => select(state) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
it('preserves form choices when project data refreshes and resets on reopening', async () => {
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  const render = (open = true) => root.render(createElement(KanbanNewTaskDialog, {
    open, initialProjectId: null, projects: [{ projectId: 'p', projectName: 'Project', workspacePath: '/repo' }],
    onClose: vi.fn(), onSubmit: vi.fn()
  }))
  try {
    await act(async () => render())
    const select = document.querySelectorAll('select')[1]
    await act(async () => { select.value = 'b'; select.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(select.value).toBe('b')
    await act(async () => render())
    expect(select.value).toBe('b')
    await act(async () => render(false))
    await act(async () => render())
    expect(document.querySelectorAll('select')[1].value).toBe('a')
  } finally { await act(async () => root.unmount()); host.remove() }
})
