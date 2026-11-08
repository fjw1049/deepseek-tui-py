import { cacheSettingsSnapshot, getSettingsSnapshot } from '../lib/settings-snapshot'
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
  AppearanceSettingsPanel: ({ form, onPatch }: { form: AppSettingsV1; onPatch: (patch: object) => void }) =>
    createElement('button', { 'data-current-theme': form.theme, onClick: () => onPatch({ theme: 'light' }) }, 'edit-theme')
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
  const stubImport = (plan: object) => {
    const request = vi.fn(async (path: string, _method?: string, _body?: string) =>
      ({ ok: true, body: path === '/v1/data/import/inspect' ? JSON.stringify(plan) : '{}' }))
    vi.stubGlobal('dsGui', { runtimeRequest: request, pickDataImportPath: async () => ({ path: '/tmp/archive.zip', canceled: false }) })
    return () => request.mock.calls.filter((args: unknown[]) => args[0] === '/v1/data/import')
  }
  const conversations = { has_conversations: true, threads: 3, settings: [] }

  it.each(['cancel', 'merge'])('%s has explicit request semantics', async (choice) => {
    const writes = stubImport(conversations)
    await act(async () => root.render(createElement(DataSettingsPanel)))
    await act(async () => button('dataImportAction').click())
    await act(async () => button(choice === 'cancel' ? 'cancel' : 'dataImportMerge').click())
    if (choice === 'cancel') expect(writes()).toHaveLength(0)
    else { expect(writes()).toHaveLength(1); expect(JSON.parse(String(writes()[0][2])).mode).toBe('merge') }
  })

  it('makes merge the primary choice and confirms replace separately', async () => {
    const writes = stubImport(conversations)
    await act(async () => root.render(createElement(DataSettingsPanel)))
    await act(async () => button('dataImportAction').click())
    const actions = [...document.querySelectorAll('[role="alertdialog"] button')]
    expect(actions.at(-1)?.textContent).toBe('dataImportMerge')
    await act(async () => button('dataImportReplace').click())
    expect(writes()).toHaveLength(0)
    const confirm = [...document.querySelectorAll('[role="alertdialog"] button')].at(-1) as HTMLButtonElement
    await act(async () => confirm.click())
    expect(writes()).toHaveLength(1)
    expect(JSON.parse(String(writes()[0][2])).mode).toBe('replace')
  })

  it('restores a settings-only bundle instead of a no-op merge', async () => {
    const writes = stubImport({ has_conversations: false, threads: 0, settings: ['config.toml'] })
    await act(async () => root.render(createElement(DataSettingsPanel)))
    await act(async () => button('dataImportAction').click())
    expect(document.body.textContent).not.toContain('dataImportMerge')
    await act(async () => button('dataImportSettingsAction').click())
    expect(JSON.parse(String(writes()[0][2])).mode).toBe('replace')
    expect(host.textContent).toContain('dataImportSettingsRestartHint')
  })

  it('lists every storage category largest first and links browser data to its settings', async () => {
    const inventory = {
      events_bytes: 1, checkpoints_bytes: 1, sessions_bytes: 0, thread_count: 1, message_count: 2,
      total_bytes: 30, storage_total_bytes: 600, log_keep_hours: 168, workspace_dir: '/h/workspace',
      categories: [
        { key: 'conversations', bytes: 30 }, { key: 'browser', bytes: 300 }, { key: 'workspace', bytes: 100 },
        { key: 'logs', bytes: 50 }, { key: 'worktrees', bytes: 0 }, { key: 'other', bytes: 120 }
      ].map(category => ({ ...category, reveal_path: category.key === 'worktrees' ? null : '/storage/' + category.key }))
    }
    const reveal = vi.fn(async (_path: string) => undefined)
    vi.stubGlobal('dsGui', {
      showItemInFolder: reveal,
      runtimeRequest: async (path: string) => ({ ok: true, body: path === '/v1/data/inventory' ? JSON.stringify(inventory) : '{}' })
    })
    await act(async () => root.render(createElement(DataSettingsPanel)))
    const labels = [...host.querySelectorAll('li .font-medium.leading-5')].map((el) => el.textContent)
    expect(labels).toEqual(['dataCatBrowser', 'dataCatWorkspace', 'dataCatLogs', 'dataCatConversations', 'dataCatWorktrees', 'dataCatOther'])
    expect(host.textContent).toContain('dataCatLogsDesc{"period":"dataPeriodDays{\\"count\\":7}"}')
    await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="dataCatManage"]')!.click())
    expect(state.openSettings).toHaveBeenCalledWith('browser')
    const actions = [...host.querySelectorAll<HTMLButtonElement>('li button')]
    expect(actions).toHaveLength(6)
    expect(actions.every(action => !action.textContent?.trim() && action.title && action.getAttribute('aria-label'))).toBe(true)
    for (const action of actions.filter(action => action.getAttribute('aria-label') !== 'dataCatManage')) {
      await act(async () => action.click())
    }
    expect(reveal.mock.calls.map(call => call[0])).toEqual([
      '/storage/browser', '/storage/workspace', '/storage/logs', '/storage/conversations', '/storage/other'
    ])
  })

  it('explains a blocked clear instead of a bare failure', async () => {
    vi.stubGlobal('dsGui', {
      runtimeRequest: async (path: string) => path === '/v1/data/clear-history'
        ? { ok: false, status: 409, body: JSON.stringify({ detail: { message: 'unpublished', error: 'history_blocked' } }) }
        : { ok: true, body: '{}' }
    })
    await act(async () => root.render(createElement(DataSettingsPanel)))
    for (let step = 0; step < 3; step += 1) {
      const target = step === 0
        ? button('dataClearHistoryAction')
        : [...document.querySelectorAll('[role="alertdialog"] button')].at(-1) as HTMLButtonElement
      await act(async () => target.click())
    }
    expect(host.textContent).toContain('dataErrorHistoryBlocked')
  })

  it('shows cached storage immediately on reentry and retains it if refresh fails', async () => {
    const request = vi.fn(async (path: string) => ({ ok: true, body: JSON.stringify(
      path === '/v1/data/inventory'
        ? { total_bytes: 1024, events_bytes: 0, checkpoints_bytes: 0, sessions_bytes: 0, thread_count: 1, message_count: 2 }
        : {}
    ) }))
    vi.stubGlobal('dsGui', { runtimeRequest: request })
    await act(async () => root.render(createElement(DataSettingsPanel)))
    expect(host.textContent).toContain('1 KB')
    await act(async () => root.render(null))
    await act(async () => root.render(createElement(DataSettingsPanel)))
    expect(request.mock.calls.filter(([path]) => path === '/v1/data/inventory')).toHaveLength(1)
    expect(host.textContent).toContain('1 KB')
    await act(async () => root.render(null))
    vi.spyOn(Date, 'now').mockReturnValue(Date.now() + 31_000)
    request.mockRejectedValueOnce(new Error('Offline'))
    await act(async () => root.render(createElement(DataSettingsPanel)))
    expect(host.textContent).toContain('1 KB')
    expect(host.textContent).toContain('dataInventoryLoadFailed')
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
  expect(getSettingsSnapshot()?.theme).toBe('dark')
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


it('shows the startup snapshot immediately, refreshes before editing, and reopens with saved settings', async () => {
  const initial = normalizeAppSettings({ theme: 'dark', deepseek: { apiKey: 'test', port: 7878 } } as AppSettingsV1)
  let finish!: (value: AppSettingsV1) => void
  const getSettings = vi.fn(() => new Promise<AppSettingsV1>(resolve => { finish = resolve }))
  const save = vi.fn(async (value: AppSettingsV1) => value)
  vi.stubGlobal('dsGui', { getSettings, setSettings: save })
  cacheSettingsSnapshot(initial)
  await act(async () => root.render(createElement(SettingsView)))
  expect(button('edit-theme').getAttribute('data-current-theme')).toBe('dark')
  expect(host.querySelector<HTMLElement>('.ds-settings-page')!.inert).toBe(true)
  // The handler also rejects synthetic edits while stale content is on display.
  await act(async () => button('edit-theme').click())
  expect(save).not.toHaveBeenCalled()
  await act(async () => finish(initial))
  expect(host.querySelector<HTMLElement>('.ds-settings-page')!.inert).toBe(false)
  await act(async () => button('edit-theme').click())
  await act(async () => requestLeaveSettings())
  expect(save).toHaveBeenCalledTimes(1)
  expect(getSettingsSnapshot()?.theme).toBe('light')
  await act(async () => root.render(null))
  await act(async () => root.render(createElement(SettingsView)))
  expect(button('edit-theme').getAttribute('data-current-theme')).toBe('light')
  expect(host.textContent).not.toBe('loading')
  await act(async () => finish({ ...initial, theme: 'dark' }))
  expect(button('edit-theme').getAttribute('data-current-theme')).toBe('dark')
})
