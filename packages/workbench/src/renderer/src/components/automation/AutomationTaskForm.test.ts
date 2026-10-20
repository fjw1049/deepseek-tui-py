// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { AutomationTaskForm } from './AutomationTaskForm'
const { t, update, confirm, back } = vi.hoisted(() => ({ confirm: vi.fn(async () => false), back: vi.fn(), t: (key: string) => key, update: vi.fn(async (_id: string, input: unknown) => input) }))
vi.mock('../../lib/automation-runtime-client', async (original) => ({ ...await original<typeof import('../../lib/automation-runtime-client')>(), updateAutomation: update }))
vi.mock('../../lib/confirm-dialog', () => ({ confirmAsync: confirm }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }))
vi.mock('../../store/chat-store', () => ({ useChatStore: (s: any) => s({ setRoute() {} }) }))
vi.mock('../../lib/resolve-channel-delivery', () => ({ loadChannelDeliveryState: async () => ({ feishuDefault: 'chat-default', emailDefault: '', feishuChannelReady: true, wecomChannelReady: false, emailChannelReady: false }) }))
vi.mock('../settings/SettingsSelect', () => ({ SettingsSelect: (p: any) => createElement('select', { value: p.value, onChange: p.onChange }, p.children) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root: ReturnType<typeof createRoot>; let host: HTMLDivElement
afterEach(async () => { await act(async () => root?.unmount()); host?.remove(); vi.clearAllMocks() })
const render = async (initialAutomation?: any) => {
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  await act(async () => root.render(createElement(AutomationTaskForm, { runtimeReady: true, workspaceRoot: '/a', onBackToChat: back, onOpenAutomationSettings() {}, onOpenRuntimeSettings() {}, initialAutomation })))
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
  const select = Array.from(host.querySelectorAll('select')).find(s => Array.from(s.options).some(o => o.value === 'once'))!
  expect(select.value).toBe('once')
  const input = host.querySelector<HTMLInputElement>('input[type="datetime-local"]')!
  expect(new Date(input.value).toISOString()).toBe('2026-10-10T01:00:00.000Z')
})

it('does not rearm a completed one-shot or change its timezone when only saving metadata', async () => {
  await render({ id: 'done', name: 'Done', prompt: 'hello', status: 'completed', timezone: 'Asia/Shanghai', schedule: null, next_run_at: null, last_run_at: '2026-01-01T01:00:00Z', cwds: ['/a'], delivery: {} })
  const save = [...host.querySelectorAll('button')].find(button => button.textContent === 'automationSave')!
  await act(async () => save.click())
  expect(update).toHaveBeenLastCalledWith('done', expect.objectContaining({ run_at: undefined, status: undefined, timezone: 'Asia/Shanghai', delivery: undefined }))
})

const record = { id: 'daily', name: 'Daily', prompt: 'hello', status: 'active', timezone: 'Asia/Shanghai', schedule: '0 10 * * *', cwds: ['/a', '/b'], delivery: { mode: 'wecom', best_effort: true } }
const save = async () => { await act(async () => [...host.querySelectorAll('button')].find(b => b.textContent === 'automationSave')!.click()) }
it('restores daily time and permits metadata saves with an unavailable existing delivery channel', async () => {
  await render(record)
  expect(host.querySelector<HTMLInputElement>('input[type="time"]')?.value).toBe('10:00')
  expect(host.textContent).toContain('automationEditStatusLabel')
  expect(host.textContent).not.toContain('automationStatusActive')
  await save()
  expect(update).toHaveBeenLastCalledWith('daily', expect.objectContaining({ schedule: '0 10 * * *', cwds: undefined, delivery: undefined }))
})
it('does not silently attach the current workspace to a task with no workspace', async () => {
  await render({ ...record, cwds: [] })
  await save()
  expect(update).toHaveBeenLastCalledWith('daily', expect.objectContaining({ cwds: undefined }))
})
it('asks before discarding edits, and stays when the user cancels', async () => {
  await render(record)
  const select = host.querySelector('select')!
  await act(async () => { select.value = 'paused'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  await act(async () => [...host.querySelectorAll('button')].find(b => b.textContent === 'cancel')!.click())
  expect(confirm).toHaveBeenCalledWith('automationDiscardChanges')
  expect(back).not.toHaveBeenCalled()
})
it('blocks changing to an unconfigured delivery channel', async () => {
  await render({ ...record, delivery: {} })
  const select = Array.from(host.querySelectorAll('select')).find(s => Array.from(s.options).some(o => o.value === 'wecom'))!
  await act(async () => { select.value = 'wecom'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  await save()
  expect(update).not.toHaveBeenCalled()
  expect(host.querySelector('[role="alert"]')?.textContent).toBe('automationDeliveryWecomNotConfigured')
})

it('does not ask to discard an untouched task', async () => {
  await render(record)
  await act(async () => [...host.querySelectorAll('button')].find(b => b.textContent === 'cancel')!.click())
  expect(confirm).not.toHaveBeenCalled()
  expect(back).toHaveBeenCalledOnce()
})
it('rejects changing a recurring task to a one-shot time in the past', async () => {
  await render({ ...record, next_run_at: '2020-01-01T01:00:00Z' })
  const select = Array.from(host.querySelectorAll('select')).find(s => Array.from(s.options).some(o => o.value === 'once'))!
  await act(async () => { select.value = 'once'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  await save()
  expect(update).not.toHaveBeenCalled()
  expect(host.querySelector('[role="alert"]')?.textContent).toBe('automationError_once_at_future')
})
it('uses the selected channel target when switching delivery modes', async () => {
  await render({ ...record, delivery: { mode: 'email', to: 'original@example.com' } })
  const select = Array.from(host.querySelectorAll('select')).find(s => Array.from(s.options).some(o => o.value === 'feishu'))!
  await act(async () => { select.value = 'feishu'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  await save()
  expect(update).toHaveBeenLastCalledWith('daily', expect.objectContaining({ delivery: { mode: 'feishu', to: 'chat-default', best_effort: false } }))
})

it('offers human-readable frequencies and keeps cron out of the main choices', async () => {
  await render(record)
  const select = Array.from(host.querySelectorAll('select')).find(s => Array.from(s.options).some(o => o.value === 'weekdays'))!
  expect(Array.from(select.options).map(o => o.value)).toEqual(['daily', 'weekdays', 'weekly', 'hourly', 'once'])
  expect(host.querySelector('input[placeholder="0 9 * * 1-5"]')).toBeNull()
  await act(async () => { select.value = 'weekdays'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(host.textContent).toContain('automationSummaryWeekdays')
  await save()
  expect(update).toHaveBeenLastCalledWith('daily', expect.objectContaining({ schedule: '0 10 * * MON,TUE,WED,THU,FRI' }))
})
it('prefills the advanced expression from the visible schedule', async () => {
  await render(record)
  await act(async () => host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click())
  expect(host.querySelector<HTMLInputElement>('input[placeholder="0 9 * * 1-5"]')?.value).toBe('0 10 * * *')
  await save()
  expect(update).toHaveBeenLastCalledWith('daily', expect.objectContaining({ schedule: '0 10 * * *' }))
})
it('preserves an existing special rule and exposes it in advanced settings', async () => {
  await render({ ...record, schedule: '0 9 1 * *' })
  expect(host.querySelector<HTMLInputElement>('input[placeholder="0 9 * * 1-5"]')?.value).toBe('0 9 1 * *')
  expect(host.querySelector('details')?.open).toBe(true)
  await save()
  expect(update).toHaveBeenLastCalledWith('daily', expect.objectContaining({ schedule: '0 9 1 * *' }))
})

it('returns to the previous simple frequency when advanced timing is switched off', async () => {
  await render({ ...record, schedule: '0 10 * * MON,FRI' })
  const checkbox = host.querySelector<HTMLInputElement>('input[type="checkbox"]')!
  await act(async () => checkbox.click())
  await act(async () => checkbox.click())
  const select = Array.from(host.querySelectorAll('select')).find(s => Array.from(s.options).some(o => o.value === 'weekly'))!
  expect(select.value).toBe('weekly')
  await save()
  expect(update).toHaveBeenLastCalledWith('daily', expect.objectContaining({ schedule: '0 10 * * MON,FRI' }))
})
