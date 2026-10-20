// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { AppSettingsV1 } from '@shared/app-settings'
import { CuaSettingsPanel } from './CuaSettingsPanel'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, string>) => options ? `${key}:${options.state}` : key
  })
}))

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const getDeepseekConfigFile = vi.fn()
const onUpdate = vi.fn()
let host: HTMLDivElement
let root: Root

beforeEach(() => {
  vi.clearAllMocks()
  Object.assign(window, { dsGui: { platform: 'darwin', getDeepseekConfigFile } })
  host = document.createElement('div')
  root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()) })

async function render(form: Partial<AppSettingsV1>): Promise<HTMLSelectElement[]> {
  await act(async () => root.render(createElement(CuaSettingsPanel, { form: form as AppSettingsV1, onUpdate })))
  return [...host.querySelectorAll('select')]
}

it('shows the value inherited from config.toml and lets the user explicitly disable it', async () => {
  getDeepseekConfigFile.mockResolvedValue({ content: '[cua]\nenabled = true\n' })
  const [enabled, chrome] = await render({})
  expect(enabled!.value).toBe('inherit')
  expect(enabled!.selectedOptions[0]!.textContent).toBe('cuaInherited:cuaOn')
  // An absent switch is off in the runtime.
  expect(chrome!.selectedOptions[0]!.textContent).toBe('cuaInherited:cuaOff')
  expect(chrome!.disabled).toBe(false)
  await act(async () => {
    enabled!.value = 'false'
    enabled!.dispatchEvent(new Event('change', { bubbles: true }))
  })
  expect(onUpdate).toHaveBeenCalledWith({ cuaEnabled: false })
  const [, chromeAfter] = await render({ cuaEnabled: false })
  expect(chromeAfter!.disabled).toBe(true)
})

it('disables Chrome while computer use is inherited as off', async () => {
  getDeepseekConfigFile.mockResolvedValue({ content: 'api_key = "x"\n' })
  const [enabled, chrome] = await render({})
  expect(enabled!.selectedOptions[0]!.textContent).toBe('cuaInherited:cuaOff')
  expect(chrome!.disabled).toBe(true)
})

it('says when the inherited value could not be read', async () => {
  getDeepseekConfigFile.mockRejectedValue(new Error('denied'))
  const [enabled, chrome] = await render({})
  expect(enabled!.selectedOptions[0]!.textContent).toBe('cuaInheritedUnknown')
  expect(chrome!.disabled).toBe(false)
})

it('explains instead of offering controls on unsupported platforms', async () => {
  Object.assign(window, { dsGui: { platform: 'win32', getDeepseekConfigFile } })
  expect(await render({})).toHaveLength(0)
  expect(host.textContent).toContain('cuaUnsupported')
  expect(getDeepseekConfigFile).not.toHaveBeenCalled()
})
