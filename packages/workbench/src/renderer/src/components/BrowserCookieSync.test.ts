// @vitest-environment happy-dom
import { act, createElement, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, expect, it, vi } from 'vitest'
import { BrowserCookieSync, type CookieSyncState } from './BrowserCookieSync'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const api = vi.hoisted(() => vi.fn())
vi.mock('./BrowserWorkspace', () => ({ browserRequest: api }))
const confirm = vi.hoisted(() => vi.fn<(message: string) => Promise<boolean>>())
vi.mock('../lib/confirm-dialog', () => ({ confirmAsync: confirm }))

let sitesResponse: () => unknown
let nativeCookies = false
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear(); sitesResponse = () => ({ sites: chromeSites }); nativeCookies = false
  Object.assign(window, { dsGui: { platform: 'linux', hasBrowserCookies: async () => nativeCookies } })
})

const initial: CookieSyncState = { consent: 'pending', profile: null, status: 'idle', count: 0, skipped: 0 }
const chromeSites = [
  { site: 'example.test', count: 3, sensitive: false },
  { site: 'news.test', count: 1, sensitive: false },
  { site: 'bank.test', count: 2, sensitive: true }
]

async function mount(profiles = [{ id: 'Default', name: 'Personal' }], state = initial, manage = false, anchor?: DOMRect, agentBusy = false, selectedSites: string[] = [], blank = false, settingsDialog = false) {
  let saved = state
  let selected = selectedSites
  api.mockReset().mockImplementation(async (_thread, path: string, body) => {
    if (path.startsWith('/cookie-sync/sites')) return sitesResponse()
    if (body?.action === 'clear') saved = { ...saved, has_saved_cookies: false, status: 'cleared', count: 0, domains: 0 }
    else if (body) saved = { ...saved, consent: body.action === 'skip' ? 'skipped' : body.action === 'disable' ? 'disabled' : 'enabled',
      profile: body.profile ?? saved.profile, status: body.action === 'skip' ? 'idle' : 'synced', count: 2, domains: 1 }
    if (body?.sites) selected = body.sites
    return { ...saved, has_saved_cookies: saved.has_saved_cookies || saved.count > 0, profiles, selected_sites: selected }
  })
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  const close = vi.fn()
  let requestUpdate = (): void => {}
  function Harness() {
    const [open, setOpen] = useState(manage)
    const [updateRequest, setUpdateRequest] = useState(0)
    requestUpdate = () => setUpdateRequest(count => count + 1)
    return createElement(BrowserCookieSync, { threadId: 'one', generation: 4, manage: open, anchor, agentBusy, blank, updateRequest, settingsDialog,
      onOpen: () => setOpen(true), onClose: () => { close(); setOpen(false) } })
  }
  await act(async () => root.render(createElement(Harness)))
  const button = (text: string): HTMLButtonElement => [...(settingsDialog ? document.body : host).querySelectorAll('button')].find(b => b.textContent === text || b.getAttribute('aria-label') === text)!
  const site = (name: string): HTMLInputElement => [...host.querySelectorAll('label')].find(l => l.textContent?.startsWith(name))!.querySelector('input')!
  const check = async (name: string): Promise<void> => { await act(async () => site(name).click()) }
  const update = async (): Promise<void> => { await act(async () => requestUpdate()) }
  return { host, root, button, site, check, close, update, unmount: async () => { await act(async () => root.unmount()); host.remove() } }
}

const invite = (selectedSites: string[] = []) => mount(undefined, initial, false, undefined, false, selectedSites, true)

it('invites on an empty tab, selects the only source, and sends no cookie values through the UI', async () => {
  const h = await invite()
  try {
    expect(api).toHaveBeenCalledTimes(1)
    expect(h.host.textContent).toContain('browserCookieInviteTitle')
    expect(h.host.textContent).not.toContain('browserCookieHint')
    await act(async () => h.button('browserCookieInviteImport').click())
    expect(h.host.querySelector('[role=dialog]')).not.toBeNull()
    // Opened from the invitation it is a focused import dialog, without the management options.
    expect(h.host.querySelector('.ds-browser-cookie-modal')).not.toBeNull()
    expect(h.host.textContent).toContain('browserCookieImportTitle')
    expect(h.host.textContent).toContain('browserCookieImportHint')
    expect(h.host.textContent).not.toContain('browserCookieClear')
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
  confirm.mockReset().mockResolvedValue(false)
  const h = await mount(undefined, initial, true)
  try {
    expect(h.host.textContent).toContain('browserCookieSitesSensitive')
    expect(h.site('bank.test').checked).toBe(false)
    await h.check('bank.test')
    await act(async () => h.button('browserCookieEnable').click())
    expect(confirm).toHaveBeenCalledWith('browserCookieSensitiveConfirm')
    expect(api.mock.calls.every(call => !call[2])).toBe(true)
  } finally { await h.unmount() }
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
  const h = await invite()
  try {
    await act(async () => h.button('browserCookieInviteImport').click())
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

it('hides the invitation for this launch on Not now, and for good on Do not show again', async () => {
  const later = await invite()
  await act(async () => later.button('browserCookieInviteLater').click())
  expect(later.host.textContent).toBe('')
  expect(api.mock.calls.every(call => !call[2])).toBe(true)
  await later.unmount()
  const relaunch = await invite()
  try { expect(relaunch.host.textContent).toBe('') } finally { await relaunch.unmount() }
  sessionStorage.clear()
  const again = await invite()
  await act(async () => again.button('browserCookieInviteNever').click())
  await again.unmount()
  sessionStorage.clear()
  const never = await invite()
  try { expect(never.host.textContent).toBe('') } finally { await never.unmount() }
})

it('does not treat closing settings opened from the menu as Not now', async () => {
  const h = await mount(undefined, initial, true, undefined, false, [], true)
  try {
    await act(async () => h.button('browserCookieDismiss').click())
    expect(h.host.textContent).toContain('browserCookieInviteTitle')
    await act(async () => h.button('browserCookieInviteImport').click())
    await act(async () => h.button('browserCookieCancel').click())
    expect(h.host.textContent).toBe('')
  } finally { await h.unmount() }
})

it('invites again on the same empty tab after clearing login data', async () => {
  nativeCookies = true
  confirm.mockReset().mockResolvedValue(true)
  const h = await mount(undefined, initial, true, undefined, false, [], true)
  try {
    nativeCookies = false
    await act(async () => h.button('browserCookieClear').click())
    expect(api.mock.calls.filter(call => call[2]).at(-1)?.[2].action).toBe('clear')
    expect(h.host.textContent).toContain('browserCookieFeedback_cleared')
    await act(async () => h.button('browserCookieDismiss').click())
    expect(h.host.textContent).toContain('browserCookieInviteTitle')
  } finally { await h.unmount() }
})

it('keeps inviting while the built-in browser has no cookies, even after a past skip', async () => {
  for (const state of [initial, { ...initial, consent: 'skipped' as const }]) {
    const h = await mount(undefined, state, false, undefined, false, [], true)
    try { expect(h.host.textContent).toContain('browserCookieInviteTitle') } finally { await h.unmount() }
  }
})

it('stays quiet when cookies exist, outside an empty tab, or without Chrome', async () => {
  nativeCookies = true
  const native = await invite()
  try { expect(native.host.textContent).toBe('') } finally { await native.unmount() }
  nativeCookies = false
  const saved = await mount(undefined, { ...initial, has_saved_cookies: true }, false, undefined, false, [], true)
  try { expect(saved.host.textContent).toBe('') } finally { await saved.unmount() }
  const page = await mount()
  try { expect(page.host.textContent).toBe('') } finally { await page.unmount() }
  const noChrome = await mount([], initial, false, undefined, false, [], true)
  try { expect(noChrome.host.textContent).toBe('') } finally { await noChrome.unmount() }
})

it('updates configured sites in place from the menu', async () => {
  const h = await mount(undefined, { ...initial, consent: 'enabled', profile: 'Default', status: 'synced' }, false, undefined, false, ['example.test'])
  try {
    await h.update()
    expect(api.mock.calls.filter(call => call[2]).at(-1)?.[2]).toEqual({ action: 'sync', generation: 4 })
    expect(h.host.querySelector('[role=dialog]')).toBeNull()
    expect(h.host.querySelector('[role=status]')?.textContent).toContain('browserCookieFeedback_synced')
  } finally { await h.unmount() }
})

it('does not replay an earlier update request when the panel mounts again', async () => {
  await mount(undefined, { ...initial, consent: 'enabled', profile: 'Default', status: 'synced' }, false, undefined, false, ['example.test']).then(h => h.unmount())
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  const open = vi.fn()
  try {
    await act(async () => root.render(createElement(BrowserCookieSync, { threadId: 'one', generation: 4, manage: false, updateRequest: 3, onOpen: open, onClose: () => {} })))
    expect(open).not.toHaveBeenCalled()
    expect(api.mock.calls.every(call => !call[2])).toBe(true)
  } finally { await act(async () => root.unmount()); host.remove() }
})

it('opens the import panel when updating before any site was chosen', async () => {
  const h = await mount()
  try {
    await h.update()
    expect(h.host.querySelector('[role=dialog]')).not.toBeNull()
    expect(api.mock.calls.every(call => !call[2])).toBe(true)
  } finally { await h.unmount() }
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

it('portals settings management outside the scrolling page and restores focus on close', async () => {
  const trigger = document.createElement('button'); document.body.append(trigger); trigger.focus()
  const h = await mount(undefined, { ...initial, consent: 'enabled', status: 'cleared', profile: 'Default' }, true, undefined, false, ['example.test'], false, true)
  try {
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]')!
    expect(h.host.contains(dialog)).toBe(false)
    expect(dialog.parentElement?.parentElement).toBe(document.body)
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(api.mock.calls.every(call => !call[2])).toBe(true)
    expect(dialog.textContent).toContain('browserCookieStatus_cleared')
    expect(dialog.textContent).toContain('browserCookieSelected')
    await act(async () => dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expect(document.activeElement).toBe(trigger)
  } finally { await h.unmount(); trigger.remove() }
})

it('keeps the settings manager open when a nested clear confirmation is canceled', async () => {
  let resolve!: (approved: boolean) => void
  confirm.mockImplementationOnce(() => new Promise<boolean>(done => { resolve = done }))
  const h = await mount(undefined, initial, true, undefined, false, [], false, true)
  try {
    await act(async () => h.button('browserCookieClear').click())
    await act(async () => document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })))
    expect(h.close).not.toHaveBeenCalled()
    expect(h.button('browserCookieDismiss').disabled).toBe(true)
    await act(async () => resolve(false))
    expect(document.querySelector('[role="dialog"]')).not.toBeNull()
    expect(api.mock.calls.some(call => call[2]?.action === 'clear')).toBe(false)
  } finally { await h.unmount() }
})
