// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SettingsView } from './SettingsView'
import { readPetFavoriteSlugs, writePetFavoriteSlugs } from '../lib/pet/pet-preferences'

vi.mock('react-i18next', async importOriginal => {
  const actual = await importOriginal<typeof import('react-i18next')>()
  const t = (key: string) => key
  return { ...actual, useTranslation: () => ({ t }) }
})
vi.mock('../store/chat-store', () => {
  const state = { settingsSection: 'general', composerModel: '', openSettings: vi.fn() }
  return { useChatStore: (selector: (value: typeof state) => unknown) => selector(state) }
})
vi.mock('../hooks/use-persistent-usage', () => ({ usePersistentUsage: () => ({}) }))
vi.mock('../lib/pet/pet-catalog', () => ({ resolvePetSpritesheetSrc: vi.fn().mockRejectedValue(new Error('offline')) }))

const catalog = Array.from({ length: 20 }, (_, i) => ({
  slug: `pet-${i}`, displayName: `Pet ${i}`, kind: 'creature', submittedBy: null,
  spritesheetUrl: '', petJsonUrl: '', zipUrl: null
}))
const success = { ok: true, manifest: { pets: catalog } }
let root: ReturnType<typeof createRoot>
let container: HTMLDivElement
const requests: Array<(value: unknown) => void> = []
const fetchManifest = vi.fn()

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const storage = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', { configurable: true, value: {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value)
  } })
  requests.length = 0
  fetchManifest.mockReset().mockImplementation(() => new Promise(resolve => requests.push(resolve)))
  Object.defineProperty(window, 'dsGui', { configurable: true, value: {
    fetchPetManifest: fetchManifest,
    getSettings: vi.fn().mockResolvedValue({
      locale: 'en', workspaceRoot: '/workspace', customEndpoints: [],
      notifications: { turnComplete: true }, deepseek: { apiKey: 'test', port: 8765, autoStart: false }
    })
  } })
  container = document.createElement('div')
  root = createRoot(container)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals() })
function button(label: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll('button')).find(button => button.textContent?.includes(label))
  expect(match, label).toBeDefined()
  return match!
}

it('stops after an offline catalog failure and retries only on request', async () => {
  await act(async () => root.render(createElement(SettingsView)))
  await act(async () => requests[0]({ ok: false, message: 'offline' }))
  expect(fetchManifest).toHaveBeenCalledTimes(1)
  await act(async () => button('petMascotSavedTitle').click())
  expect(container.textContent).toContain('offline')
  await act(async () => button('petMascotRefresh').click())
  expect(fetchManifest).toHaveBeenCalledTimes(2)
  await act(async () => requests[1](success))
  expect(readPetFavoriteSlugs()).toHaveLength(15)
})

it('keeps favorites empty after removing the last entry and refreshing', async () => {
  writePetFavoriteSlugs(['pet-0'])
  await act(async () => root.render(createElement(SettingsView)))
  await act(async () => requests[0](success))
  await act(async () => button('petMascotSavedTitle').click())
  await act(async () => button('Pet 0').click())
  expect(readPetFavoriteSlugs()).toEqual([])
  expect(fetchManifest).toHaveBeenCalledTimes(1)
  await act(async () => button('petMascotRefresh').click())
  await act(async () => requests[1](success))
  expect(readPetFavoriteSlugs()).toEqual([])
})

it('shows available pets beyond the first ten catalog entries', async () => {
  writePetFavoriteSlugs(catalog.slice(0, 14).map(pet => pet.slug))
  await act(async () => root.render(createElement(SettingsView)))
  await act(async () => requests[0](success))
  await act(async () => button('petMascotSavedTitle').click())
  expect(button('Pet 14').disabled).toBe(false)
  await act(async () => button('Pet 14').click())
  expect(readPetFavoriteSlugs()).toContain('pet-14')
})
