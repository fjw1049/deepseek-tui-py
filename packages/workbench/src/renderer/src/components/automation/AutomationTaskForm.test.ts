// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { AutomationTaskForm } from './AutomationTaskForm'
const { t, update } = vi.hoisted(() => ({ t: (key: string) => key, update: vi.fn(async (_id: string, input: unknown) => input) }))
vi.mock('../../lib/automation-runtime-client', async (original) => ({ ...await original<typeof import('../../lib/automation-runtime-client')>(), updateAutomation: update }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }))
vi.mock('../../store/chat-store', () => ({ useChatStore: (s: any) => s({ setRoute() {} }) }))
vi.mock('../../lib/resolve-channel-delivery', () => ({ loadChannelDeliveryState: async () => ({ feishuDefault: 'chat-default', emailDefault: '', feishuChannelReady: true, wecomChannelReady: false, emailChannelReady: false }) }))
vi.mock('../settings/SettingsSelect', () => ({ SettingsSelect: (p: any) => createElement('select', { value: p.value, onChange: p.onChange }, p.children) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root: ReturnType<typeof createRoot>; let host: HTMLDivElement
afterEach(async () => { await act(async () => root?.unmount()); host?.remove() })
const render = async (initialAutomation?: any) => {
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  await act(async () => root.render(createElement(AutomationTaskForm, { runtimeReady: true, workspaceRoot: '/a', onBackToChat() {}, onOpenAutomationSettings() {}, onOpenRuntimeSettings() {}, initialAutomation })))
}
it('preserves an explicit none delivery selection', async () => {
  await render()
  const select = Array.from(host.querySelectorAll('select')).find(s => Array.from(s.options).some(o => o.value === 'feishu'))!
  expect(select.value).toBe('feishu')
  await act(async () => { select.value = 'none'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(select.value).toBe('none')
})
it('restores the type and local time of a one-shot automation', async () => {
  await render({ id: 'once', name: 'One', prompt: 'hello', status: 'active', schedule: null, next_run_at: '2026-10-10T01:00:00Z', cwds: ['/a'] })
  const select = Array.from(host.querySelectorAll('select')).find(s => Array.from(s.options).some(o => o.value === 'custom'))!
  expect(select.value).toBe('once')
  const input = host.querySelector<HTMLInputElement>('input[type="datetime-local"]')!
  expect(new Date(input.value).toISOString()).toBe('2026-10-10T01:00:00.000Z')
})

it('does not rearm a completed one-shot or change its timezone when only saving metadata', async () => {
  await render({ id: 'done', name: 'Done', prompt: 'hello', status: 'completed', timezone: 'Asia/Shanghai', schedule: null, next_run_at: null, last_run_at: '2026-01-01T01:00:00Z', cwds: ['/a'], delivery: {} })
  const save = [...host.querySelectorAll('button')].find(button => button.textContent === 'automationSave')!
  await act(async () => save.click())
  expect(update).toHaveBeenLastCalledWith('done', expect.objectContaining({ run_at: undefined, status: undefined, timezone: 'Asia/Shanghai', delivery: {} }))
})
