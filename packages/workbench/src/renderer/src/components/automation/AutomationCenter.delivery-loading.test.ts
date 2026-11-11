// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
const api = vi.hoisted(() => ({ t: (key: string) => key }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: api.t }) }))
vi.mock('./AutomationTaskForm', () => ({ AutomationTaskForm: () => null }))
vi.mock('../../lib/resolve-channel-delivery', async original => ({
  ...await original<typeof import('../../lib/resolve-channel-delivery')>(),
  loadChannelDeliveryState: async () => ({})
}))
vi.mock('../../lib/automation-runtime-client', async original => ({
  ...await original<typeof import('../../lib/automation-runtime-client')>(),
  listAutomations: async () => [{ id: 'audit', name: 'KNOWN_VISIBLE_AUTOMATION', prompt: 'read', enabled: true, schedule: '0 * * * *', created_at: '', updated_at: '', cwds: [] }],
  listAutomationRuns: async () => [],
  listPendingAutomationDeliveries: async () => { throw Error('PENDING_ENDPOINT_404') }
}))
import { AutomationCenter } from './AutomationCenter'
it('pending endpoint failure displays an error but does not discard automation rows', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(AutomationCenter, {
      runtimeReady: true, workspaceRoot: '/repo', onOpenRuntimeSettings() {}
    })))
    expect(host.textContent).toContain('KNOWN_VISIBLE_AUTOMATION')
    expect(host.querySelector('[role=status]')?.textContent).toContain('PENDING_ENDPOINT_404')
    expect(host.textContent).toContain('automationDeliveryLoadFailed')
  } finally { await act(async () => root.unmount()); host.remove() }
})
