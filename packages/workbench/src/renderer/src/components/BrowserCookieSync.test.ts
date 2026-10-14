// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { BrowserCookieSync, type CookieSyncState } from './BrowserCookieSync'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const api = vi.hoisted(() => vi.fn())
vi.mock('./BrowserWorkspace', () => ({ browserRequest: api }))

const initial: CookieSyncState = { consent: 'pending', profile: null, status: 'idle', count: 0, skipped: 0 }

async function mount(profiles = [{ id: 'Default', name: 'Personal' }], state = initial, manage = false) {
  api.mockReset().mockImplementation(async (_thread, _path, body) => body
    ? { ...state, consent: body.action === 'skip' ? 'skipped' : 'enabled', profile: body.profile, status: body.action === 'skip' ? 'idle' : 'synced', count: 2, domains: 1 }
    : { ...state, profiles })
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  const close = vi.fn()
  await act(async () => root.render(createElement(BrowserCookieSync, { threadId: 'one', generation: 4, manage, onClose: close })))
  const button = (text: string): HTMLButtonElement => [...host.querySelectorAll('button')].find(b => b.textContent === text)!
  return { host, root, button, close, unmount: async () => { await act(async () => root.unmount()); host.remove() } }
}

it('asks once, selects the only source, and sends no cookie values through the UI', async () => {
  const h = await mount()
  try {
    expect(api).toHaveBeenCalledTimes(1)
    expect(h.host.textContent).toContain('browserCookieHint')
    expect(h.host.querySelector('select')).toBeNull()
    await act(async () => h.button('browserCookieEnable').click())
    expect(api).toHaveBeenLastCalledWith('one', '/cookie-sync', { action: 'enable', profile: 'Default', generation: 4 })
    expect(h.host.querySelector('[role=status]')?.textContent).toBe('browserCookieStatus_synced')
    await act(async () => h.button('browserCookieDismiss').click())
    expect(h.host.querySelector('section')).toBeNull()
  } finally { await h.unmount() }
})

it('does not pick an account when Chrome has multiple profiles', async () => {
  const h = await mount([{ id: 'Default', name: 'Personal' }, { id: 'Profile 1', name: 'Work' }])
  try {
    expect(h.button('browserCookieEnable').disabled).toBe(true)
    await act(async () => { const field = h.host.querySelector('select')!; field.value = 'Profile 1'; field.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(h.button('browserCookieEnable').disabled).toBe(false)
    await act(async () => h.button('browserCookieEnable').click())
    expect(api.mock.calls.at(-1)?.[2].profile).toBe('Profile 1')
  } finally { await h.unmount() }
})

it('continues without Chrome and remembers dismissal', async () => {
  const h = await mount([])
  try {
    expect(h.host.textContent).toContain('browserCookieNoChrome')
    expect(h.button('browserCookieEnable')).toBeUndefined()
    await act(async () => h.button('browserCookieContinue').click())
    expect(api.mock.calls.at(-1)?.[2].action).toBe('skip')
    expect(h.host.querySelector('section')).toBeNull()
  } finally { await h.unmount() }
})

it('offers an explicit retry after a read failure and can stop synchronization', async () => {
  const h = await mount(undefined, { ...initial, consent: 'enabled', profile: 'Default', status: 'unavailable' }, true)
  try {
    expect(h.host.querySelector('[role=status]')?.textContent).toBe('browserCookieStatus_unavailable')
    await act(async () => h.button('browserCookieResync').click())
    expect(api.mock.calls.at(-1)?.[2].action).toBe('sync')
    await act(async () => h.button('browserCookieDisable').click())
    expect(api.mock.calls.at(-1)?.[2].action).toBe('disable')
  } finally { await h.unmount() }
})

it('shows progress and keeps an empty import result visible', async () => {
  const h = await mount()
  let finish: (value: unknown) => void = () => {}
  api.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  try {
    await act(async () => h.button('browserCookieEnable').click())
    expect(h.host.querySelector('[role=status]')?.textContent).toBe('browserCookieStatus_syncing')
    expect(h.button('browserCookieSyncing').disabled).toBe(true)
    await act(async () => finish({ ...initial, consent: 'enabled', profile: 'Default', status: 'empty' }))
    expect(h.host.querySelector('[role=status]')?.textContent).toBe('browserCookieStatus_empty')
    expect(h.button('browserCookieResync')).toBeDefined()
  } finally { await h.unmount() }
})
