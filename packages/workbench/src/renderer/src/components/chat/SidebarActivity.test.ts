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
    await act(async () => root.render(createElement(SidebarActivity, { rows, activeThreadId: null, runtimeReady: true, onSelectThread: select, onDismiss: vi.fn() })))
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
