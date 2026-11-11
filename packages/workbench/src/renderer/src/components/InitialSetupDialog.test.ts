// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { InitialSetupPanel } from './InitialSetupDialog'

const actions = vi.hoisted(() => ({
  openSettings: vi.fn(), closeInitialSetup: vi.fn(), applyI18nFromSettings: vi.fn(),
  reloadUiSettings: vi.fn(), probeRuntime: vi.fn()
}))
vi.mock('../store/chat-store', () => ({ useChatStore: (selector: (s: typeof actions) => unknown) => selector(actions) }))
vi.mock('../lib/apply-theme', () => ({ applyTheme: vi.fn() }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('./settings/GlassSegmentedControl', () => ({ GlassSegmentedControl: ({ value }: { value: string }) => createElement('output', null, value) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let container: HTMLDivElement
let root: Root
const settings = () => ({ locale: 'en', theme: 'system', workspaceRoot: '/workspace',
  deepseek: { apiKey: '', approvalPolicy: 'never' },
  llmProviders: { deepseek: { apiKey: '' }, kimi: { apiKey: 'test-key' } } })
let getSettings: ReturnType<typeof vi.fn>
let setSettings: ReturnType<typeof vi.fn>
beforeEach(() => {
  vi.clearAllMocks()
  getSettings = vi.fn().mockResolvedValue(settings())
  setSettings = vi.fn().mockImplementation(async (value) => value)
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { getSettings, setSettings } })
  container = document.createElement('div'); document.body.append(container); root = createRoot(container)
})
afterEach(async () => { await act(async () => root.unmount()); container.remove() })
const render = async () => { await act(async () => root.render(createElement(InitialSetupPanel))) }
const click = async (label: string) => {
  const button = [...container.querySelectorAll('button')].find(b => b.textContent === label)!
  await act(async () => button.click())
}
it('saves another configured provider and preserves the displayed legacy policy', async () => {
  await render()
  expect(container.querySelector('output')?.textContent).toBe('never')
  await click('firstRunSave')
  expect(setSettings).toHaveBeenCalledWith(expect.objectContaining({ deepseek: expect.objectContaining({ approvalPolicy: 'never' }) }))
  expect(actions.closeInitialSetup).toHaveBeenCalled()
})
it('blocks saving when every provider key is empty', async () => {
  const value = settings(); value.llmProviders.kimi.apiKey = ''; getSettings.mockResolvedValue(value)
  await render(); await click('firstRunSave')
  expect(setSettings).not.toHaveBeenCalled()
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('firstRunApiKeyValidation')
})
it('recovers from a settings load failure with retry', async () => {
  getSettings.mockRejectedValueOnce(new Error('offline'))
  await render()
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('setupLoadError')
  await click('setupRetry')
  expect(container.querySelector('input[aria-label="apiKey"]')).not.toBeNull()
})
