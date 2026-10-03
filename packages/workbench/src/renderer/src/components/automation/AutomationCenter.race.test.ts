// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
const api = vi.hoisted(() => ({ listAutomationRuns: vi.fn(), t: (key: string) => key }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: api.t }) }))
vi.mock('./AutomationTaskForm', () => ({ AutomationTaskForm: () => null }))
vi.mock('./AutomationListCard', () => ({ AutomationListCard: (props: { title: string; onOpenDetails?: () => void }) => createElement('button', { onClick: props.onOpenDetails }, props.title) }))
vi.mock('../../lib/resolve-channel-delivery', async (original) => ({ ...await original<typeof import('../../lib/resolve-channel-delivery')>(), loadChannelDeliveryState: async () => ({}) }))
vi.mock('../../lib/automation-runtime-client', async (original) => ({
  ...await original<typeof import('../../lib/automation-runtime-client')>(),
  listAutomations: async () => ['A', 'B'].map(id => ({ id, name: id, prompt: id, schedule: '0 * * * *', timezone: 'UTC', status: 'active' })),
  listAutomationRuns: api.listAutomationRuns
}))
import { AutomationCenter } from './AutomationCenter'
it('ignores a late response from the previously selected automation', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  let finishA!: (value: unknown[]) => void
  api.listAutomationRuns.mockImplementation((id: string) => id === 'A'
    ? new Promise(resolve => { finishA = resolve })
    : Promise.resolve([{ id: 'B-run', automation_id: 'B', status: 'succeeded', task_id: 'B-task', created_at: '', scheduled_for: '' }]))
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(AutomationCenter, { runtimeReady: true, workspaceRoot: '/repo', onOpenRuntimeSettings() {} })))
    const button = (name: string) => [...host.querySelectorAll('button')].find(item => item.textContent === name)!
    await act(async () => button('A').click())
    await act(async () => button('B').click())
    expect(document.body.textContent).toContain('B-task')
    await act(async () => finishA([{ id: 'A-run', automation_id: 'A', status: 'succeeded', task_id: 'A-task', created_at: '', scheduled_for: '' }]))
    expect(document.body.textContent).toContain('B-task')
    expect(document.body.textContent).not.toContain('A-task')
  } finally { await act(async () => root.unmount()); host.remove() }
})
