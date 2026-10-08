// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  discuss: vi.fn(),
  t: (key: string) => key
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: api.t }) }))
vi.mock('./AutomationTaskForm', () => ({ AutomationTaskForm: () => null }))
vi.mock('./AutomationListCard', () => ({
  AutomationListCard: (props: { title: string; onOpenDetails?: () => void }) =>
    createElement('button', { onClick: props.onOpenDetails }, props.title)
}))
vi.mock('../../lib/resolve-channel-delivery', async (original) => ({
  ...await original<typeof import('../../lib/resolve-channel-delivery')>(),
  loadChannelDeliveryState: async () => ({})
}))
vi.mock('../../lib/automation-runtime-client', async (original) => ({
  ...await original<typeof import('../../lib/automation-runtime-client')>(),
  listAutomations: async () => [{
    id: 'job', name: 'Project check', prompt: 'check', schedule: '0 * * * *',
    timezone: 'UTC', status: 'active'
  }],
  listAutomationRuns: async () => [
    { id: 'finished', automation_id: 'job', status: 'completed', created_at: '', scheduled_for: '' },
    { id: 'running', automation_id: 'job', status: 'running', created_at: '', scheduled_for: '' }
  ],
  openAutomationDiscussion: api.discuss
}))
import { AutomationCenter } from './AutomationCenter'

it('opens the result conversation and prevents duplicate clicks while opening', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const openThread = vi.fn()
  let resolve!: (value: { thread_id: string }) => void
  api.discuss.mockImplementation(() => new Promise(done => { resolve = done }))
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(AutomationCenter, {
      runtimeReady: true, workspaceRoot: '/repo', onOpenRuntimeSettings() {},
      onOpenThread: openThread
    })))
    const buttons = () => [...document.querySelectorAll('button')]
    await act(async () => buttons().find(item => item.textContent === 'Project check')!.click())
    const discuss = buttons().filter(item => item.textContent === 'automationDiscussResult')
    expect(discuss).toHaveLength(1)
    await act(async () => discuss[0].click())
    expect(api.discuss).toHaveBeenCalledWith('job', 'finished')
    expect((discuss[0] as HTMLButtonElement).disabled).toBe(true)
    await act(async () => discuss[0].click())
    expect(api.discuss).toHaveBeenCalledTimes(1)
    await act(async () => resolve({ thread_id: 'thr_result' }))
    expect(openThread).toHaveBeenCalledWith('thr_result')
  } finally {
    await act(async () => root.unmount())
    host.remove()
  }
})
