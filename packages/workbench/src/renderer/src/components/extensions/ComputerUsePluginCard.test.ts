// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { ComputerUsePluginCard } from './ComputerUsePluginCard'
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('./use-plugin-now', () => ({ usePluginNow: vi.fn() }))
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
    expect(disable.disabled).toBe(!installed)
    await act(async () => disable.click())
    if (installed) {
      expect(setSettings).toHaveBeenCalledWith({ cuaEnabled: false })
      await act(async () => host.querySelector('button')!.click())
      expect(document.body.textContent).toContain('computerUseApplying')
      await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
    } else {
      expect(setSettings).not.toHaveBeenCalled()
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
    const findButton = (label: string) => [...host.querySelectorAll('button')].find(b => b.textContent === label)!
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
    expect(runtimeRequest).toHaveBeenCalledTimes(2)
    expect(document.body.textContent).toContain('computerUseApplying')
  } finally { await act(async () => root.unmount()) }
})
