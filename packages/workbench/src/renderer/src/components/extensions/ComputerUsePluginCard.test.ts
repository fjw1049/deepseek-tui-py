// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { ComputerUsePluginCard } from './ComputerUsePluginCard'
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('./start-chat-with-plugin', () => ({ usePluginNow: vi.fn() }))
vi.mock('../../lib/settings-snapshot', () => ({ cacheSettingsSnapshot: vi.fn() }))

it.each([false, true])('reports component availability and saves opt-out: installed=%s', async installed => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const setSettings = vi.fn().mockResolvedValue({ cuaEnabled: false })
  Object.assign(window, { dsGui: {
    runtimeRequest: vi.fn()
      .mockResolvedValueOnce({ ok: true, body: JSON.stringify({ supported: true, installed, enabled: true }) })
      .mockResolvedValue({ ok: true, body: JSON.stringify({ supported: true, installed, enabled: false }) }),
    setSettings
  } })
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(ComputerUsePluginCard)))
    expect(host.textContent).not.toContain('computerUseDisable')
    await act(async () => host.querySelector('button')!.click())
    expect(document.body.textContent).toContain(installed ? 'computerUseReady' : 'computerUseMissing')
    expect(document.body.textContent).not.toContain('pluginManage')
    await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
    await act(async () => host.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')!.click())
    const disable = [...host.querySelectorAll('button')].find(b => b.textContent === 'computerUseDisable')!
    expect(disable.disabled).toBe(false)
    await act(async () => disable.click())
    {
      expect(setSettings).toHaveBeenCalledWith({ cuaEnabled: false })
      await act(async () => host.querySelector('button')!.click())
      expect(document.body.textContent).toContain('computerUseApplying')
      await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
    }
    expect(host.textContent).toContain('computerUseTitle')
  } finally { await act(async () => root.unmount()) }
})

it('keeps the toggle locked until the runtime confirms the change', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  let finishSave!: (value: { cuaEnabled: boolean }) => void
  const setSettings = vi.fn(() => new Promise(resolve => { finishSave = resolve }))
  const runtimeRequest = vi.fn()
    .mockResolvedValueOnce({ ok: true, body: JSON.stringify({ supported: true, installed: true, enabled: true }) })
    .mockResolvedValue({ ok: true, body: JSON.stringify({ supported: true, installed: true, enabled: false }) })
  Object.assign(window, { dsGui: { setSettings, runtimeRequest } })
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(ComputerUsePluginCard)))
    const openMenu = () => host.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')!.click()
    const findButton = (label: string) => [...host.querySelectorAll('button')].find(b => b.textContent === label || b.getAttribute('title') === label)!
    await act(async () => openMenu())
    const toggle = findButton('computerUseDisable')
    await act(async () => { toggle.click(); toggle.click() })
    expect(setSettings).toHaveBeenCalledOnce()
    await act(async () => openMenu())
    expect(findButton('computerUseDisable').disabled).toBe(true)
    expect(findButton('pluginUseNow').disabled).toBe(true)
    await act(async () => finishSave({ cuaEnabled: false }))
    expect(findButton('computerUseEnable').disabled).toBe(false)
    await act(async () => host.querySelector('button')!.click())
    // The dialog also reads setup state; status itself is read twice.
    expect(runtimeRequest.mock.calls.filter(call => call[0] === '/v1/cua/status')).toHaveLength(2)
    expect(document.body.textContent).toContain('computerUseApplying')
  } finally { await act(async () => root.unmount()) }
})

it('lists always-allowed apps and revokes only the chosen identity', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const status = JSON.stringify({ supported: true, installed: true, enabled: true })
  const notes = { name: 'Notes', bundleId: 'com.apple.Notes', installed: true }
  const runtimeRequest = vi.fn(async (path: string) => ({
    ok: true,
    body: path === '/v1/cua/status' ? status
      : JSON.stringify({ apps: path === '/v1/cua/apps/revoke' ? [] : [notes] })
  }))
  Object.assign(window, { dsGui: { platform: 'darwin', setSettings: vi.fn(), runtimeRequest } })
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(ComputerUsePluginCard)))
    await act(async () => host.querySelector('button')!.click())
    expect(document.body.textContent).toContain('Notes')
    const revoke = [...document.body.querySelectorAll('button')].find(b => b.getAttribute('title') === 'computerUseRevoke')!
    await act(async () => revoke.click())
    expect(runtimeRequest).toHaveBeenCalledWith('/v1/cua/apps/revoke', 'POST', JSON.stringify({ app: 'com.apple.Notes' }))
    expect(document.body.textContent).toContain('computerUseApprovedAppsEmpty')
    await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
  } finally { await act(async () => root.unmount()) }
})

it('can refresh a missing component after installation', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  let installed = false
  Object.assign(window, { dsGui: { runtimeRequest: vi.fn(async () => ({
    ok: true, body: JSON.stringify({ supported: true, installed, enabled: true })
  })) } })
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(ComputerUsePluginCard)))
    await act(async () => host.querySelector('button')!.click())
    expect(document.body.textContent).toContain('computerUseMissing')
    installed = true
    await act(async () => [...document.body.querySelectorAll('button')].find(b => b.textContent === 'computerUseRefresh')!.click())
    expect(document.body.textContent).toContain('computerUseReady')
  } finally { await act(async () => root.unmount()) }
})

it('reconciles permissions when the revoke response is lost', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  let revoked = false
  Object.assign(window, { dsGui: { platform: 'darwin', runtimeRequest: vi.fn(async (path: string) => {
    if (path.endsWith('/revoke')) { revoked = true; throw new Error('connection lost') }
    return { ok: true, body: JSON.stringify(path.endsWith('/status')
      ? { supported: true, installed: true, enabled: true }
      : { apps: revoked ? [] : [{ name: 'Notes', bundleId: 'com.apple.Notes' }] }) }
  }) } })
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(ComputerUsePluginCard)))
    await act(async () => host.querySelector('button')!.click())
    await act(async () => [...document.body.querySelectorAll('button')].find(b => b.getAttribute('title') === 'computerUseRevoke')!.click())
    expect(document.body.textContent).toContain('computerUseApprovedAppsEmpty')
    expect(document.body.textContent).not.toContain('computerUseAppsError')
  } finally { await act(async () => root.unmount()) }
})
