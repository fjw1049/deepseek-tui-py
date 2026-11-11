// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ resolve: vi.fn(), t: (key: string) => key }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: api.t }) }))
vi.mock('./AutomationTaskForm', () => ({ AutomationTaskForm: () => null }))
vi.mock('../../lib/resolve-channel-delivery', async original => ({
  ...await original<typeof import('../../lib/resolve-channel-delivery')>(),
  loadChannelDeliveryState: async () => ({})
}))
vi.mock('../../lib/automation-runtime-client', async original => ({
  ...await original<typeof import('../../lib/automation-runtime-client')>(),
  listAutomations: async () => [],
  listPendingAutomationDeliveries: async () => [{
    id: 'trigger-run', automation_id: '_http_triggers', automation_name: 'HTTP trigger',
    delivery_state: 'uncertain', status: 'completed', created_at: '', scheduled_for: '',
    delivery_snapshot: { summary: 'Original report body', automation_name: 'HTTP trigger',
      config: { mode: 'wecom', to: 'secret-webhook-key' } }
  }],
  resolveAutomationDelivery: api.resolve
}))
import { AutomationCenter } from './AutomationCenter'

it.each([
  ['received', 'automationDeliveryReceived', 'sent'],
  ['retry', 'automationDeliveryRetryConfirmed', 'pending']
])('resolves an HTTP-trigger delivery with %s and prevents duplicate clicks', async (action, label, state) => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  api.resolve.mockReset()
  let finish!: (value: unknown) => void
  api.resolve.mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(AutomationCenter, {
      runtimeReady: true, workspaceRoot: '/repo', onOpenRuntimeSettings() {}
    })))
    expect(host.textContent).toContain('HTTP trigger')
    expect(host.textContent).toContain('Original report body')
    expect(host.textContent).not.toContain('secret-webhook-key')
    const button = [...host.querySelectorAll('button')].find(item => item.textContent === label)!
    await act(async () => button.click())
    expect(api.resolve).toHaveBeenCalledWith('_http_triggers', 'trigger-run', action)
    expect(button.disabled).toBe(true)
    await act(async () => button.click())
    expect(api.resolve).toHaveBeenCalledTimes(1)
    await act(async () => finish({ id: 'trigger-run', automation_id: '_http_triggers', delivery_state: state }))
    expect(host.textContent).not.toContain('HTTP trigger')
  } finally {
    await act(async () => root.unmount())
    host.remove()
  }
})
