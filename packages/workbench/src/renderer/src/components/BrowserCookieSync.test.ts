// @vitest-environment happy-dom
import { act, createElement, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, expect, it, vi } from 'vitest'
import { BrowserCookieSync, type CookieSyncState } from './BrowserCookieSync'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const api = vi.hoisted(() => vi.fn())
vi.mock('./BrowserWorkspace', () => ({ browserRequest: api }))

let sitesResponse: () => unknown
beforeEach(() => { localStorage.clear(); sitesResponse = () => ({ sites: chromeSites }) })

const initial: CookieSyncState = { consent: 'pending', profile: null, status: 'idle', count: 0, skipped: 0 }
const chromeSites = [
  { site: 'example.test', count: 3, sensitive: false },
  { site: 'news.test', count: 1, sensitive: false },
  { site: 'bank.test', count: 2, sensitive: true }
]

async function mount(profiles = [{ id: 'Default', name: 'Personal' }], state = initial, manage = false, anchor?: DOMRect, agentBusy = false, selectedSites: string[] = []) {
  let saved = state
  let selected = selectedSites
  api.mockReset().mockImplementation(async (_thread, path: string, body) => {
    if (path.startsWith('/cookie-sync/sites')) return sitesResponse()
    if (body) saved = { ...saved, consent: body.action === 'skip' ? 'skipped' : body.action === 'disable' ? 'disabled' : 'enabled',
      profile: body.profile ?? saved.profile, status: body.action === 'skip' ? 'idle' : 'synced', count: 2, domains: 1 }
    if (body?.sites) selected = body.sites
    return { ...saved, profiles, selected_sites: selected }
  })
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  const close = vi.fn()
  function Harness() {
    const [open, setOpen] = useState(manage)
    return createElement(BrowserCookieSync, { threadId: 'one', generation: 4, manage: open, anchor, agentBusy,
      onOpen: () => setOpen(true), onClose: () => { close(); setOpen(false) } })
  }
  await act(async () => root.render(createElement(Harness)))
  const button = (text: string): HTMLButtonElement => [...host.querySelectorAll('button')].find(b => b.textContent === text || b.getAttribute('aria-label') === text)!
  const site = (name: string): HTMLInputElement => [...host.querySelectorAll('label')].find(l => l.textContent?.startsWith(name))!.querySelector('input')!
  const check = async (name: string): Promise<void> => { await act(async () => site(name).click()) }
  return { host, root, button, site, check, close, unmount: async () => { await act(async () => root.unmount()); host.remove() } }
}

it('asks once, selects the only source, and sends no cookie values through the UI', async () => {
  const h = await mount()
  try {
    expect(api).toHaveBeenCalledTimes(1)
    expect(h.host.textContent).toContain('browserCookieInvite')
    expect(h.host.textContent).not.toContain('browserCookieHint')
    await act(async () => h.button('browserCookieSetup').click())
    expect(h.host.querySelector('[role=dialog]')).not.toBeNull()
    expect(h.host.textContent).toContain('browserCookieHint')
    expect(h.host.querySelector('select')).toBeNull()
    // Nothing is preselected: only checked sites are imported.
    expect(h.button('browserCookieEnableEmpty').disabled).toBe(true)
    await h.check('example.test')
    await act(async () => h.button('browserCookieEnable').click())
    expect(api).toHaveBeenCalledWith('one', '/cookie-sync', { action: 'enable', profile: 'Default', sites: ['example.test'], generation: 4 })
    expect(h.host.querySelector('[role=status]')?.textContent).toContain('browserCookieFeedback_synced')
    await act(async () => h.button('browserCookieDismiss').click())
    expect(h.host.querySelector('section')).toBeNull()
  } finally { await h.unmount() }
})

it('does not offer a sync that would pause a running agent task', async () => {
  const h = await mount(undefined, initial, true, undefined, true)
  try {
    await h.check('example.test')
    expect(h.button('browserCookieEnable').disabled).toBe(true)
    expect(h.host.textContent).toContain('browserCookieAgentBusy')
  } finally { await h.unmount() }
})

it('confirms before importing sensitive sites', async () => {
  const confirm = vi.fn(() => false)
  vi.stubGlobal('confirm', confirm)
  const h = await mount(undefined, initial, true)
  try {
    expect(h.host.textContent).toContain('browserCookieSitesSensitive')
    expect(h.site('bank.test').checked).toBe(false)
    await h.check('bank.test')
    await act(async () => h.button('browserCookieEnable').click())
    expect(confirm).toHaveBeenCalledWith('browserCookieSensitiveConfirm')
    expect(api.mock.calls.every(call => !call[2])).toBe(true)
  } finally { vi.unstubAllGlobals(); await h.unmount() }
})

it('resyncs the saved sites without asking again', async () => {
  const h = await mount(undefined, { ...initial, consent: 'enabled', profile: 'Default', status: 'synced' }, true, undefined, false, ['example.test'])
  try {
    expect(h.host.textContent).toContain('browserCookieSelected')
    expect(h.host.querySelector('input[type=checkbox]')).toBeNull()
    await act(async () => h.button('browserCookieResync').click())
    expect(api.mock.calls.filter(call => call[2]).at(-1)?.[2]).toEqual({ action: 'sync', generation: 4 })
  } finally { await h.unmount() }
})

it('lets the user deselect saved sites', async () => {
  const h = await mount(undefined, { ...initial, consent: 'enabled', profile: 'Default', status: 'synced' }, true, undefined, false, ['example.test'])
  try {
    await act(async () => h.button('browserCookieChangeSites').click())
    expect(h.site('example.test').checked).toBe(true)
    await h.check('example.test')
    await act(async () => h.button('browserCookieEnableEmpty').click())
    expect(api.mock.calls.filter(call => call[2]).at(-1)?.[2]).toEqual({ action: 'sync', sites: [], generation: 4 })
  } finally { await h.unmount() }
})

it('explains a macOS refusal and retries reading Chrome sites', async () => {
  sitesResponse = () => ({ sites: [], error: 'permission' })
  const h = await mount(undefined, initial, true)
  try {
    expect(h.host.querySelector('[role=alert]')?.textContent).toContain('browserCookieSitesPermission')
    expect(h.button('browserCookieEnableEmpty').disabled).toBe(true)
    sitesResponse = () => ({ sites: chromeSites })
    await act(async () => h.button('browserCookieSitesRetry').click())
    expect(h.host.querySelector('[role=alert]')).toBeNull()
    expect(h.site('example.test')).toBeDefined()
  } finally { await h.unmount() }
})

it('selects all ordinary sites at once and leaves sensitive ones to the user', async () => {
  const h = await mount(undefined, initial, true)
  try {
    const all = (): HTMLInputElement => h.site('browserCookieSelectAllSafe')
    await act(async () => all().click())
    expect([h.site('example.test').checked, h.site('news.test').checked, h.site('bank.test').checked]).toEqual([true, true, false])
    await act(async () => all().click())
    expect(h.site('example.test').checked || h.site('news.test').checked).toBe(false)
    await h.check('news.test')
    expect(all().indeterminate).toBe(true)
    await act(async () => all().click())
    await act(async () => h.button('browserCookieEnable').click())
    expect(api.mock.calls.filter(call => call[2]).at(-1)?.[2].sites).toEqual(['example.test', 'news.test'])
  } finally { await h.unmount() }
})

it('does not pick an account when Chrome has multiple profiles', async () => {
  const h = await mount([{ id: 'Default', name: 'Personal' }, { id: 'Profile 1', name: 'Work' }], initial, true)
  try {
    expect(h.button('browserCookieEnableEmpty').disabled).toBe(true)
    await act(async () => { const field = h.host.querySelector('select')!; field.value = 'Profile 1'; field.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(api.mock.calls.some(call => call[1] === '/cookie-sync/sites?profile=Profile%201')).toBe(true)
    await h.check('example.test')
    expect(h.button('browserCookieEnable').disabled).toBe(false)
    await act(async () => h.button('browserCookieEnable').click())
    expect(api.mock.calls.filter(call => call[2]).at(-1)?.[2].profile).toBe('Profile 1')
  } finally { await h.unmount() }
})

it('continues without Chrome and remembers dismissal', async () => {
  const h = await mount([], initial, true)
  try {
    expect(h.host.textContent).toContain('browserCookieNoChrome')
    expect(h.button('browserCookieEnable')).toBeUndefined()
    await act(async () => h.button('browserCookieContinue').click())
    expect(api.mock.calls.filter(call => call[2]).at(-1)?.[2].action).toBe('skip')
    expect(h.host.querySelector('section')).toBeNull()
  } finally { await h.unmount() }
})

it('offers an explicit retry after a read failure and can stop synchronization', async () => {
  const h = await mount(undefined, { ...initial, consent: 'enabled', profile: 'Default', status: 'unavailable' }, true, undefined, false, ['example.test'])
  try {
    expect(h.host.querySelector('[role=status]')?.textContent).toBe('browserCookieStatus_unavailable')
    await act(async () => h.button('browserCookieResync').click())
    expect(api.mock.calls.filter(call => call[2]).at(-1)?.[2].action).toBe('sync')
    await act(async () => h.button('browserCookieDetails').click())
    await act(async () => h.button('browserCookieDisable').click())
    expect(api.mock.calls.filter(call => call[2]).at(-1)?.[2].action).toBe('disable')
  } finally { await h.unmount() }
})

it('shows progress and keeps an empty import result visible', async () => {
  const h = await mount(undefined, initial, true)
  let finish: (value: unknown) => void = () => {}
  api.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
  try {
    await h.check('example.test')
    await act(async () => h.button('browserCookieEnable').click())
    expect(h.host.querySelector('[role=status]')?.textContent).toBe('browserCookieStatus_syncing')
    expect(h.button('browserCookieSyncing').disabled).toBe(true)
    await act(async () => finish({ ...initial, consent: 'enabled', profile: 'Default', status: 'empty' }))
    expect(h.host.querySelector('[role=status]')?.textContent).toBe('browserCookieStatus_empty')
    expect(h.button('browserCookieResync')).toBeDefined()
  } finally { await h.unmount() }
})

for (const status of ['synced', 'partial', 'unavailable']) {
  it(`does not replay a historical ${status} result on mount`, async () => {
    const h = await mount(undefined, { ...initial, consent: 'enabled', status })
    try { expect(h.host.textContent).toBe('') } finally { await h.unmount() }
  })
}

it('closes settings with Escape without granting consent', async () => {
  const h = await mount()
  try {
    await act(async () => h.button('browserCookieSetup').click())
    expect(document.activeElement).toBe(h.button('browserCookieDismiss'))
    await act(async () => h.host.querySelector('[role=dialog]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(h.host.querySelector('[role=dialog]')).toBeNull()
    expect(api.mock.calls.every(call => !call[2])).toBe(true)
  } finally { await h.unmount() }
})

it('removes successful import feedback after four seconds', async () => {
  const h = await mount(undefined, initial, true)
  await h.check('example.test')
  vi.useFakeTimers()
  try {
    await act(async () => h.button('browserCookieEnable').click())
    expect(h.host.textContent).toContain('browserCookieFeedback_synced')
    await act(async () => vi.advanceTimersByTime(4000))
    expect(h.host.textContent).toBe('')
  } finally { vi.useRealTimers(); await h.unmount() }
})

it('persists skipping from the compact invitation', async () => {
  const h = await mount()
  try {
    await act(async () => h.button('browserCookieSkip').click())
    expect(api).toHaveBeenCalledWith('one', '/cookie-sync', { action: 'skip', generation: 4 })
    expect(h.host.textContent).toBe('')
  } finally { await h.unmount() }
})

for (const state of [{ ...initial, has_saved_cookies: true }, { ...initial, count: 2 }, { ...initial, consent: 'skipped' as const }]) {
  it('stays quiet when login data exists or the invitation was skipped', async () => {
    const h = await mount(undefined, state)
    try { expect(h.host.textContent).toBe('') } finally { await h.unmount() }
  })
}

it('does not repeat an ignored invitation after reopening, but permits manual setup', async () => {
  const first = await mount()
  expect(first.host.textContent).toContain('browserCookieInvite')
  await first.unmount()
  const second = await mount()
  try { expect(second.host.textContent).toBe('') } finally { await second.unmount() }
  const manual = await mount(undefined, initial, true)
  try { expect(manual.button('browserCookieEnableEmpty')).toBeDefined() } finally { await manual.unmount() }
})

it('anchors the panel below and right-aligned with its source and dismisses on outside click', async () => {
  const width = vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(320)
  const height = vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(240)
  const h = await mount(undefined, initial, true, new DOMRect(600, 100, 180, 30))
  try {
    const dialog = document.querySelector<HTMLElement>('[role=dialog]')!
    expect(dialog.style.position).toBe('')
    expect(dialog.style.left).toBe('460px')
    expect(dialog.style.top).toBe('138px')
    expect(dialog.querySelector('details')!.open).toBe(false)
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 5)) })
    await act(async () => document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })))
    expect(document.querySelector('[role=dialog]')).toBeNull()
  } finally { await h.unmount(); width.mockRestore(); height.mockRestore() }
})

it('keeps an edge-anchored panel inside the window', async () => {
  const width = vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(320)
  const height = vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(240)
  const h = await mount(undefined, initial, true, new DOMRect(0, window.innerHeight - 20, 40, 20))
  try {
    const dialog = document.querySelector<HTMLElement>('[role=dialog]')!
    expect(dialog.style.left).toBe('12px')
    expect(dialog.style.top).toBe(`${window.innerHeight - 252}px`)
  } finally { await h.unmount(); width.mockRestore(); height.mockRestore() }
})

it('positions within the browser pane when it is offset from the window edge', async () => {
  const container = document.createElement('div')
  Object.defineProperties(container, { clientWidth: { value: 700 }, clientHeight: { value: 800 } })
  container.getBoundingClientRect = () => new DOMRect(900, 80, 700, 800)
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', { configurable: true, get: () => container })
  const width = vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(320)
  const height = vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(240)
  const h = await mount(undefined, initial, true, new DOMRect(1550, 100, 30, 30))
  try {
    const dialog = h.host.querySelector<HTMLElement>('[role=dialog]')!
    expect(dialog.style.left).toBe('360px')
    expect(dialog.style.top).toBe('58px')
  } finally { await h.unmount(); Reflect.deleteProperty(HTMLElement.prototype, 'offsetParent'); width.mockRestore(); height.mockRestore() }
})
