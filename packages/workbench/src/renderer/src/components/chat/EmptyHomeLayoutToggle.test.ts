// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { defaultAppearanceSettings } from '@shared/appearance'
import { applyAppearance, getEmptyHomeLayout } from '../../lib/apply-appearance'
import { useChatStore } from '../../store/chat-store'
import { EmptyHomeLayoutToggle } from './EmptyHomeLayoutToggle'

vi.mock('../../store/chat-store', async () => {
  const { create } = await import('zustand')
  return { useChatStore: create(() => ({
    route: 'chat', blocks: [], busy: false, liveAssistant: '', liveReasoning: ''
  })) }
})
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root
const setSettings = vi.fn()

beforeEach(() => {
  setSettings.mockReset().mockImplementation(async ({ appearance }) => ({
    appearance: { ...defaultAppearanceSettings(), ...appearance }
  }))
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { setSettings } })
  applyAppearance({ ...defaultAppearanceSettings(), emptyHomeLayout: 'normal' })
  useChatStore.setState({ route: 'chat', blocks: [], busy: false, liveAssistant: '', liveReasoning: '' })
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
})

it('preserves the home layout toggle, saving both directions and updating its icon state', async () => {
  await act(async () => root.render(createElement(EmptyHomeLayoutToggle)))
  const button = container.querySelector('button')!
  expect(button.title).toBe('emptyHomeLayoutToggleToSimple')
  expect(button.querySelector('.lucide-layout-dashboard')).not.toBeNull()
  await act(async () => button.click())
  expect(setSettings).toHaveBeenLastCalledWith({ appearance: { emptyHomeLayout: 'simple' } })
  expect(getEmptyHomeLayout()).toBe('simple')
  expect(button.getAttribute('aria-pressed')).toBe('true')
  expect(button.querySelector('.rotate-180')).not.toBeNull()
  expect(button.title).toBe('emptyHomeLayoutToggleToNormal')
  await act(async () => button.click())
  expect(setSettings).toHaveBeenLastCalledWith({ appearance: { emptyHomeLayout: 'normal' } })
  expect(getEmptyHomeLayout()).toBe('normal')
  expect(button.getAttribute('aria-pressed')).toBe('false')
})

it('keeps the original home visibility conditions without showing a notification bell elsewhere', async () => {
  await act(async () => root.render(createElement(EmptyHomeLayoutToggle)))
  for (const patch of [
    { route: 'kanban' as const },
    { blocks: [{ kind: 'user' as const, id: 'query', text: 'Hello' }] },
    { busy: true },
    { liveAssistant: 'response' },
    { liveReasoning: 'thinking' }
  ]) {
    await act(async () => useChatStore.setState(patch))
    expect(container.querySelector('button')).toBeNull()
    expect(container.querySelector('.lucide-bell')).toBeNull()
    await act(async () => useChatStore.setState({ route: 'chat', blocks: [], busy: false, liveAssistant: '', liveReasoning: '' }))
    expect(container.querySelector('.lucide-layout-dashboard')).not.toBeNull()
  }
})
