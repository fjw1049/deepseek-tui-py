// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import type { AppSettingsV1 } from '@shared/app-settings'
import { CuaSettingsPanel } from './CuaSettingsPanel'

it('shows inherited settings honestly and lets the user explicitly disable them', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  const root = createRoot(host)
  const onUpdate = vi.fn()
  const form = { locale: 'zh' } as AppSettingsV1
  try {
    await act(async () => root.render(createElement(CuaSettingsPanel, { form, onUpdate })))
    const [enabled, chrome] = host.querySelectorAll('select')
    expect(enabled.value).toBe('inherit')
    expect(chrome.value).toBe('inherit')
    expect(chrome.disabled).toBe(false)
    expect(host.textContent).toContain('继承配置文件')
    await act(async () => {
      enabled.value = 'false'
      enabled.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(onUpdate).toHaveBeenCalledWith({ cuaEnabled: false })
    await act(async () => root.render(createElement(CuaSettingsPanel, {
      form: { ...form, cuaEnabled: false }, onUpdate
    })))
    expect(host.querySelectorAll('select')[1].disabled).toBe(true)
  } finally {
    await act(async () => root.unmount())
  }
})
