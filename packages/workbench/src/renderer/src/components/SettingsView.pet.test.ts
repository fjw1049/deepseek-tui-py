// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SettingsView } from './SettingsView'
import { readPetSlug } from '../lib/pet/pet-preferences'

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

const popular = [
  { slug: 'capvolt', displayName: 'Pikachu', kind: 'creature', submittedBy: 'Ann', likeCount: 68, installCount: 10 },
  { slug: 'deepseek', displayName: 'deepseek酱', kind: 'character', submittedBy: null, likeCount: 50, installCount: 9 }
]
let root: ReturnType<typeof createRoot>
let container: HTMLDivElement
const fetchManifest = vi.fn()
const fetchPopularPets = vi.fn()
const resolvePetThumbnails = vi.fn()

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const storage = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', { configurable: true, value: {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value)
  } })
  fetchManifest.mockReset()
  fetchPopularPets.mockReset().mockResolvedValue({ source: 'live', pets: popular })
  resolvePetThumbnails.mockReset().mockImplementation(async (slugs: string[]) =>
    Object.fromEntries(slugs.map(slug => [slug, `data:image/webp;base64,${slug}`])))
  Object.defineProperty(window, 'dsGui', { configurable: true, value: {
    fetchPetManifest: fetchManifest,
    fetchPopularPets,
    resolvePetThumbnails,
    getSettings: vi.fn().mockResolvedValue({
      locale: 'en', workspaceRoot: '/workspace', customEndpoints: [],
      notifications: { turnComplete: true }, deepseek: { apiKey: 'test', port: 8765, autoStart: false }
    })
  } })
  container = document.createElement('div')
  root = createRoot(container)
})
afterEach(async () => { await act(async () => root.unmount()); vi.unstubAllGlobals() })

function tile(name: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll<HTMLButtonElement>('button[aria-pressed]'))
    .find(button => button.title === name)
  expect(match, name).toBeDefined()
  return match!
}
it('shows the popular ranking with thumbnails and switches pets with one click', async () => {
  await act(async () => root.render(createElement(SettingsView)))
  expect(fetchPopularPets).toHaveBeenCalledOnce()
  expect(fetchManifest).not.toHaveBeenCalled()
  expect(tile('Pikachu').querySelector('img')?.getAttribute('src')).toBe('data:image/webp;base64,capvolt')
  await act(async () => tile('deepseek酱').click())
  expect(readPetSlug()).toBe('deepseek')
  expect(tile('deepseek酱').getAttribute('aria-pressed')).toBe('true')
})

it('shows only the ranking: no search box, and the full catalog is never loaded', async () => {
  await act(async () => root.render(createElement(SettingsView)))
  expect(tile('Pikachu').closest('fieldset')?.querySelector('input')).toBeNull()
  expect(fetchManifest).not.toHaveBeenCalled()
})

it('keeps a usable list when the app has no popular-pets bridge yet', async () => {
  Object.defineProperty(window, 'dsGui', { configurable: true, value: {
    fetchPetManifest: fetchManifest,
    getSettings: vi.fn().mockResolvedValue({ locale: 'en', workspaceRoot: '/workspace', customEndpoints: [],
      notifications: { turnComplete: true }, deepseek: { apiKey: 'test', port: 8765, autoStart: false } })
  } })
  await act(async () => root.render(createElement(SettingsView)))
  expect(container.querySelectorAll('button[aria-pressed]').length).toBeGreaterThanOrEqual(60)
})
