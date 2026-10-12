// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { SidebarActivity } from './SidebarActivity'
import { buildSidebarActivity } from '../../lib/sidebar-activity'

vi.mock('react-i18next', async (importOriginal) => ({
  ...await importOriginal<typeof import('react-i18next')>(),
  useTranslation: () => ({ t: (key: string) => key })
}))
globalThis.IS_REACT_ACT_ENVIRONMENT = true

it('opens exactly the selected conversation and keeps unread state untouched while browsing', async () => {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const select = vi.fn()
  const unread = { failed: true }
  const rows = buildSidebarActivity({
    threads: [{ id: 'idle', title: 'Latest idle', workspace: '/projects/other', model: '', mode: '', updatedAt: '', createdAt: '2026-10-12T00:00:00Z' }, { id: 'failed', title: 'Fix build', workspace: '/projects/demo', model: '', mode: '', updatedAt: '', latestTurnStatus: 'failed' }],
    hiddenWorkspacePaths: [], runningIds: new Set(), unreadThreadIds: unread, activeThreadId: null, activeWaiting: false
  })
  try {
    await act(async () => root.render(createElement(SidebarActivity, { rows, activeThreadId: null, runtimeReady: true, onSelectThread: select, onDismiss: vi.fn(), onArchiveThread: vi.fn(), onDeleteThread: vi.fn() })))
    expect(select).not.toHaveBeenCalled()
    expect(container.textContent).toContain('demo')
    expect(container.querySelectorAll('.ds-activity-row')).toHaveLength(2)
    expect(container.querySelectorAll('.ds-activity-group')).toHaveLength(0)
    expect(container.querySelector('.ds-activity-title')?.textContent).toBe('Latest idle')
    expect(container.querySelector('[aria-label="activityUnreadBadge"]')).not.toBeNull()
    await act(async () => container.querySelectorAll<HTMLButtonElement>('.ds-activity-row')[1].click())
    expect(select).toHaveBeenCalledExactlyOnceWith('failed')
    expect(unread.failed).toBe(true)
  } finally {
    await act(async () => root.unmount())
    container.remove()
  }
})


it('archives and deletes only the chosen conversation, with confirmation and without opening it', async () => {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const select = vi.fn()
  let finishArchive!: () => void
  const archive = vi.fn(() => new Promise<void>((resolve) => { finishArchive = resolve }))
  const remove = vi.fn(async () => {})
  const confirm = vi.fn(() => false)
  vi.stubGlobal('confirm', confirm)
  const rows = buildSidebarActivity({
    threads: [{ id: 'target', title: 'Conversation', workspace: '/demo', model: '', mode: '', updatedAt: '', latestTurnStatus: 'completed' }],
    hiddenWorkspacePaths: [], runningIds: new Set(), unreadThreadIds: {}, activeThreadId: null, activeWaiting: false
  })
  try {
    await act(async () => root.render(createElement(SidebarActivity, {
      rows, activeThreadId: null, runtimeReady: true, onSelectThread: select,
      onDismiss: vi.fn(), onArchiveThread: archive, onDeleteThread: remove
    })))
    expect(container.querySelector('.ds-activity-meta')?.textContent).toBe('demo')
    expect(container.querySelector('.ds-activity-title > span')).not.toBeNull()
    const archiveButton = container.querySelector<HTMLButtonElement>('[aria-label="sidebarThreadArchive"]')!
    const deleteButton = container.querySelector<HTMLButtonElement>('[aria-label="sidebarThreadDelete"]')!
    expect(container.querySelector('button button')).toBeNull()
    await act(async () => archiveButton.click())
    expect(archive).toHaveBeenCalledExactlyOnceWith('target')
    expect(deleteButton.disabled).toBe(true)
    await act(async () => { finishArchive() })
    expect(deleteButton.disabled).toBe(false)
    await act(async () => deleteButton.click())
    expect(confirm).toHaveBeenCalledOnce()
    expect(remove).not.toHaveBeenCalled()
    confirm.mockReturnValue(true)
    await act(async () => deleteButton.click())
    expect(remove).toHaveBeenCalledExactlyOnceWith('target')
    expect(select).not.toHaveBeenCalled()
  } finally {
    vi.unstubAllGlobals()
    await act(async () => root.unmount())
    container.remove()
  }
})

it('shows available branches, resolves worktrees separately, and reads each directory once', async () => {
  const getGitBranches = vi.fn(async (path: string) => {
    if (path === '/not-git') throw new Error('Not a repository')
    return { ok: true, currentBranch: path === '/worktree' ? 'feature/test' : 'main' }
  })
  vi.stubGlobal('dsGui', { getGitBranches })
  const container = document.createElement('div')
  const root = createRoot(container)
  const rows = buildSidebarActivity({
    threads: [
      { id: 'a', workspace: '/demo' }, { id: 'b', workspace: '/demo' },
      { id: 'c', workspace: '/demo', worktreePath: '/worktree' }, { id: 'd', workspace: '/not-git' }
    ].map((thread) => ({ ...thread, title: thread.id, model: '', mode: '', updatedAt: '', latestTurnStatus: 'completed' })),
    hiddenWorkspacePaths: [], runningIds: new Set(), unreadThreadIds: {}, activeThreadId: null, activeWaiting: false
  })
  try {
    await act(async () => root.render(createElement(SidebarActivity, {
      rows, activeThreadId: null, runtimeReady: true, onSelectThread: vi.fn(), onDismiss: vi.fn(),
      onArchiveThread: vi.fn(), onDeleteThread: vi.fn()
    })))
    expect(getGitBranches).toHaveBeenCalledTimes(3)
    expect(Array.from(container.querySelectorAll('.ds-activity-meta'), (el) => el.textContent)).toEqual([
      'demo·main', 'demo·main', 'demo·feature/test', 'not-git'
    ])
    expect(container.querySelector('[title="feature/test"]')).not.toBeNull()
  } finally {
    await act(async () => root.unmount())
    vi.unstubAllGlobals()
  }
})
