// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { normalizeAppSettings, type AppSettingsV1 } from '@shared/app-settings'
import { ConfirmDialog } from './workspace-editor/ConfirmDialog'
import { ImportMcpJsonDialog } from './extensions/ImportMcpJsonDialog'
import { WecomChannelSetup } from './channels/WecomChannelSetup'
import { DataSettingsPanel } from './settings/DataSettingsPanel'
import { SettingsView } from './SettingsView'
import { requestLeaveSettings } from '../lib/settings-leave'
import { AutomationCenter } from './automation/AutomationCenter'

const state = vi.hoisted(() => ({
  settingsSection: 'appearance', setRoute: vi.fn(), openSettings: vi.fn(),
  applyI18nFromSettings: vi.fn(async () => undefined), reloadUiSettings: vi.fn(async () => undefined),
  probeRuntime: vi.fn(async () => undefined), refreshThreads: vi.fn(async () => undefined),
  t: (key: string, values?: Record<string, unknown>) => key + (values ? JSON.stringify(values) : '')
}))
vi.mock('react-i18next', async (original) => ({ ...await original<typeof import('react-i18next')>(), useTranslation: () => ({ t: state.t, i18n: { language: 'en' } }) }))
vi.mock('../store/chat-store', () => ({ useChatStore: (select: (s: typeof state) => unknown) => select(state) }))
vi.mock('../hooks/use-persistent-usage', () => ({ usePersistentUsage: () => ({}) }))
vi.mock('./settings/AppearanceSettingsPanel', () => ({
  AppearanceSettingsPanel: ({ onPatch }: { onPatch: (patch: object) => void }) =>
    createElement('button', { onClick: () => onPatch({ theme: 'light' }) }, 'edit-theme')
}))
vi.mock('../lib/resolve-channel-delivery', () => ({
  loadChannelDeliveryState: async () => null,
  templateDeliveryCardHint: () => '', resolveDefaultDeliveryFromChannels: () => null
}))

let root: Root
let host: HTMLDivElement
function button(label: string): HTMLButtonElement {
  const el = [...document.querySelectorAll('button')].find((b) => b.textContent?.trim() === label)
  expect(el, label).toBeDefined()
  return el!
}
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  vi.clearAllMocks()
})
afterEach(() => { act(() => root.unmount()); host.remove(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('safe confirmation', () => {
  it('focuses cancel, traps Tab and restores the prior focus', async () => {
    const previous = document.createElement('button'); document.body.append(previous); previous.focus()
    const confirm = vi.fn(); const cancel = vi.fn()
    await act(async () => root.render(createElement(ConfirmDialog, { title: 'discard?', confirmLabel: 'discard', cancelLabel: 'keep', destructive: true, onConfirm: confirm, onCancel: cancel })))
    expect(document.activeElement).toBe(button('keep'))
    act(() => button('keep').dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true, cancelable: true })))
    expect(document.activeElement).toBe(button('discard'))
    act(() => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
    expect(cancel).toHaveBeenCalledOnce(); expect(confirm).not.toHaveBeenCalled()
    await act(async () => root.render(null))
    expect(document.activeElement).toBe(previous); previous.remove()
  })
})

it('shows channel failure text and keeps the test action usable', async () => {
  vi.stubGlobal('dsGui', {
    getWecomConfig: async () => ({ configured: true, config: { webhookKey: 'test' } }),
    runtimeRequest: async () => ({ ok: false, status: 502, body: JSON.stringify({ detail: { error: 'wecom_send_failed', message: 'Bad webhook' } }) })
  })
  await act(async () => root.render(createElement(WecomChannelSetup, { runtimeReady: true, onConfigured() {} })))
  await act(async () => button('channelWecomTestSend').click())
  expect(host.querySelector('[role="alert"]')?.textContent).toBe('Bad webhook')
  expect(button('channelWecomTestSend').disabled).toBe(false)
})

it('reports MCP partial failures and retries only failed entries', async () => {
  const onSubmit = vi.fn(async (id: string) => { if (id === 'bad' && onSubmit.mock.calls.length < 3) throw new Error('Write denied') })
  const onClose = vi.fn()
  await act(async () => root.render(createElement(ImportMcpJsonDialog, { open: true, onClose, isDuplicate: (id) => id === 'existing', onSubmit })))
  const input = host.ownerDocument.querySelector('textarea')!
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, JSON.stringify({ mcpServers: { good: { command: 'a' }, existing: { command: 'b' }, bad: { command: 'c' } } }))
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await act(async () => button('mcpImportSubmit').click())
  expect(document.body.textContent).toContain('"added":1,"skipped":1,"failed":1')
  expect(document.body.textContent).toContain('Write denied'); expect(onClose).not.toHaveBeenCalled()
  await act(async () => button('mcpImportRetryFailed').click())
  expect(onSubmit.mock.calls.map(([id]) => id)).toEqual(['good', 'bad', 'bad'])
  expect(document.body.textContent).toContain('"added":2,"skipped":1,"failed":0')
})

describe('data import', () => {
  it.each(['cancel', 'merge', 'replace'])('%s has explicit request semantics', async (choice) => {
    const request = vi.fn(async (_path: string, _method?: string, _body?: string) => ({ ok: true, body: '{}' }))
    vi.stubGlobal('dsGui', { runtimeRequest: request, pickDataImportPath: async () => ({ path: '/tmp/archive.zip', canceled: false }) })
    await act(async () => root.render(createElement(DataSettingsPanel)))
    await act(async () => button('dataImportAction').click())
    await act(async () => button(choice === 'cancel' ? 'cancel' : choice === 'merge' ? 'dataImportMerge' : 'dataImportReplace').click())
    const writes = request.mock.calls.filter((args: unknown[]) => args[0] === '/v1/data/import')
    if (choice === 'cancel') expect(writes).toHaveLength(0)
    else { expect(writes).toHaveLength(1); expect(JSON.parse(String(writes[0][2])).mode).toBe(choice) }
  })
})

it('retains settings after a failed leave, then retries the same draft', async () => {
  const settings = normalizeAppSettings({ locale: 'en', theme: 'dark', deepseek: { apiKey: 'test', port: 7878, approvalPolicy: 'on-request' }, log: {}, workspaceRoot: '/repo' } as AppSettingsV1)
  const save = vi.fn().mockRejectedValueOnce(new Error('Write denied')).mockImplementation(async (value) => value)
  vi.stubGlobal('dsGui', { getSettings: async () => settings, setSettings: save })
  await act(async () => root.render(createElement(SettingsView)))
  await act(async () => button('edit-theme').click())
  await act(async () => requestLeaveSettings())
  expect(state.setRoute).not.toHaveBeenCalled()
  expect(document.querySelector('[role="alertdialog"]')).not.toBeNull()
  await act(async () => button('settingsKeepEditing').click())
  expect(host.textContent).toContain('Write denied')
  await act(async () => requestLeaveSettings())
  expect(save.mock.calls[1][0].theme).toBe('light')
  expect(state.setRoute).toHaveBeenCalledWith('chat')
})

it('does not show an empty success when all automation history requests fail', async () => {
  vi.stubGlobal('dsGui', { runtimeRequest: async (path: string) => path === '/v1/automations'
    ? { ok: true, body: JSON.stringify([{ id: 'a', name: 'A', prompt: 'run', schedule: null, timezone: 'UTC', status: 'active' }]) }
    : { ok: false, body: JSON.stringify({ detail: 'Unavailable' }) } })
  await act(async () => root.render(createElement(AutomationCenter, { runtimeReady: true, workspaceRoot: '/repo', onOpenRuntimeSettings() {} })))
  await act(async () => button('automationTabRuns').click())
  expect(host.textContent).toContain('automationRunsPartialFailure')
  expect(host.textContent).not.toContain('automationAllRunsEmpty')
  expect(host.textContent).not.toContain('listReloaded')
})
