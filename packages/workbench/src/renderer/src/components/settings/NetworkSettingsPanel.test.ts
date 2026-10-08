// @vitest-environment happy-dom
import { act, createElement, type SelectHTMLAttributes } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { defaultLlmProviders, type AppSettingsV1 } from '@shared/app-settings'
import { NetworkSettingsPanel } from './NetworkSettingsPanel'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('./SettingsSelect', () => ({
  SettingsSelect: (props: SelectHTMLAttributes<HTMLSelectElement>) => createElement('select', props)
}))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container: HTMLDivElement
let root: Root
const onUpdate = vi.fn()
const form = {
  network: { mode: 'system', bypassHosts: ['devpilot.zhonganonline.com'] },
  deepseek: { baseUrl: 'https://api.deepseek.com' },
  llmProviders: defaultLlmProviders(),
  customEndpoints: [{ id: 'za', name: 'ZA', baseUrl: 'http://devpilot.zhonganonline.com/claudecode', protocol: 'anthropic', apiKey: 'secret' }]
} as AppSettingsV1

beforeEach(() => {
  vi.clearAllMocks()
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(async () => { await act(async () => root.unmount()); container.remove() })

async function render(settings = form): Promise<void> {
  await act(async () => root.render(createElement(NetworkSettingsPanel, { form: settings, onUpdate })))
}

async function editHosts(value: string): Promise<void> {
  const textarea = container.querySelector('textarea')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, value)
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await act(async () => { textarea.dispatchEvent(new FocusEvent('focusout', { bubbles: true })) })
}

it('saves valid hosts on blur and keeps invalid edits out of saved settings', async () => {
  await render()
  await editHosts('https://bad.example/path')
  expect(container.querySelector('[role="alert"]')?.textContent).toBe('networkInvalidHost')
  expect(onUpdate).not.toHaveBeenCalled()
  await editHosts(' INTERNAL.EXAMPLE \ninternal.example')
  expect(onUpdate).toHaveBeenCalledWith({ network: { mode: 'system', bypassHosts: ['internal.example'] } })
})

it('lets users clear the list and hides it in direct mode', async () => {
  await render()
  await editHosts('')
  expect(onUpdate).toHaveBeenCalledWith({ network: { mode: 'system', bypassHosts: [] } })
  await render({ ...form, network: { mode: 'direct', bypassHosts: ['devpilot.zhonganonline.com'] } })
  expect(container.querySelector('textarea')).toBeNull()
})
