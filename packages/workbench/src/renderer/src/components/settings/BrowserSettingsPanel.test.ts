// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { AppSettingsV1 } from '@shared/app-settings'
import { BrowserSettingsPanel } from './BrowserSettingsPanel'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const api = vi.hoisted(() => vi.fn())
const openSettings = vi.hoisted(() => vi.fn())
vi.mock('../BrowserWorkspace', () => ({ browserRequest: api }))
vi.mock('../BrowserCookieSync', () => ({ BrowserCookieSync: () => createElement('div', { 'data-cookie-manager': true }) }))
vi.mock('../../store/chat-store', () => ({ useChatStore: (select: (s: unknown) => unknown) => select({ openSettings }) }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
let root: Root, host: HTMLDivElement
const onUpdate = vi.fn()
beforeEach(() => {
  vi.clearAllMocks()
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  api.mockResolvedValue({ agent_enabled: true, grants: [{ thread_id: 't', site: 'https://example.com' }] })
  Object.assign(window, { dsGui: { pickWorkspaceDirectory: vi.fn(async () => ({ canceled: false, path: '/tmp/chosen' })) } })
})
afterEach(async () => { await act(async () => root.unmount()); host.remove() })
async function render(): Promise<void> {
  await act(async () => root.render(createElement(BrowserSettingsPanel, { form: {} as AppSettingsV1, onUpdate })))
}
async function click(text: string): Promise<void> {
  await act(async () => [...host.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent === text)!.click())
}
it('saves the AI control setting through the runtime, not a decorative local toggle', async () => {
  await render()
  await act(async () => host.querySelector<HTMLButtonElement>('[role="switch"]')!.click())
  expect(api).toHaveBeenCalledWith('workbench-preview', '/settings', { agent_enabled: false })
})
it('disables runtime controls when settings cannot be loaded and allows retry', async () => {
  api.mockRejectedValueOnce(new Error('offline'))
  await render()
  expect(host.querySelector<HTMLButtonElement>('[role="switch"]')!.disabled).toBe(true)
  expect(host.querySelector('[role="alert"]')).not.toBeNull()
  await click('browserRetry')
  expect(host.querySelector<HTMLButtonElement>('[role="switch"]')!.disabled).toBe(false)
})
it('revokes only the selected site and saves the chosen download directory', async () => {
  await render()
  await click('browserRevoke')
  expect(api).toHaveBeenCalledWith('workbench-preview', '/settings/revoke', { thread_id: 't', site: 'https://example.com' })
  await click('browserChange')
  expect(onUpdate).toHaveBeenCalledWith({ browserDownloadDirectory: '/tmp/chosen' })
})
it('offers the existing login manager even after the invitation was dismissed', async () => {
  await render()
  await act(async () => [...host.querySelectorAll<HTMLButtonElement>('button')].filter(b => b.textContent === 'browserManage')[1]!.click())
  expect(host.querySelector('[data-cookie-manager]')).not.toBeNull()
})

it('links external Chrome management to computer control', async () => {
  await render(); await click('browserManage')
  expect(openSettings).toHaveBeenCalledWith('computer-control')
})

it('keeps web and local link preferences separate', async () => {
  await render()
  const selectors = [...host.querySelectorAll<HTMLButtonElement>('[role="combobox"]')]
  for (const [index, key] of ['browserLinkTarget', 'browserLocalLinkTarget'].entries()) {
    await act(async () => selectors[index]!.click())
    const option = [...document.querySelectorAll<HTMLElement>('[role="option"]')].find(el => el.textContent?.includes('browserInternal'))!
    await act(async () => option.click())
    expect(onUpdate).toHaveBeenLastCalledWith({ [key]: 'internal' })
  }
})

it('does not show a failed AI control update as successful', async () => {
  await render(); api.mockRejectedValueOnce(new Error('action busy'))
  await act(async () => host.querySelector<HTMLButtonElement>('[role="switch"]')!.click())
  expect(host.querySelector('[role="switch"]')!.getAttribute('aria-checked')).toBe('true')
  expect(host.querySelector('[role="alert"]')).not.toBeNull()
})

it('saves download prompting and restores the system download directory', async () => {
  await act(async () => root.render(createElement(BrowserSettingsPanel, { form: { browserDownloadDirectory: '/tmp/chosen' } as AppSettingsV1, onUpdate })))
  const switches = [...host.querySelectorAll<HTMLButtonElement>('[role="switch"]')]
  await act(async () => switches[1]!.click())
  expect(onUpdate).toHaveBeenLastCalledWith({ browserAskDownloadLocation: false })
  await click('browserReset')
  expect(onUpdate).toHaveBeenLastCalledWith({ browserDownloadDirectory: '' })
})
