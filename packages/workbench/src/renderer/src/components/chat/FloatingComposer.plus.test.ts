// @vitest-environment happy-dom
import { act, createElement, type ComponentProps } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { FloatingComposer } from './FloatingComposer'
import { useChatStore } from '../../store/chat-store'
import i18n from '../../i18n'
vi.mock('./ReasoningEffortSelector', () => ({ ReasoningEffortSelector: () => null }))
const initial = useChatStore.getState()
let host: HTMLDivElement, root: ReturnType<typeof createRoot>
const noop = () => {}
const props: ComponentProps<typeof FloatingComposer> = {
  input: '', setInput: noop, mode: 'agent', setMode: noop, busy: false,
  runtimeReady: true, hasActiveThread: true, composerModel: 'test', composerPickList: [],
  onComposerModelChange: noop, queuedMessages: [], onRemoveQueuedMessage: noop,
  onWithdrawQueuedMessage: () => null, onSendQueuedMessageNow: noop,
  onSend: async () => true, onInterrupt: noop, onCompact: async () => {}, onFork: async () => {}, onOpenDiff: noop
}
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 800, 500))
  useChatStore.setState({ ...initial, activeThreadId: 'paste-a', workspaceRoot: '/repo', runtimeConnection: 'ready', refreshPendingUserInputs: async () => {} }, true)
  vi.stubGlobal('dsGui', { runtimeRequest: vi.fn(async () => ({ ok: true, body: JSON.stringify({ skills: [{ name: 'review', description: 'Review changes' }] }) })), pickWorkspaceFiles: vi.fn(async () => ({ ok: true, files: [] })) })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); useChatStore.setState(initial, true); vi.unstubAllGlobals(); vi.restoreAllMocks() })

const label = (key: string) => String(i18n.t(`common:${key}`))
function trigger() {
  return host.querySelector<HTMLButtonElement>(`button[aria-label="${label('composerPlusMenu')}"]`)!
}
function action(key: string) {
  return Array.from(host.querySelectorAll<HTMLButtonElement>('[role="option"]'))
    .find((button) => button.textContent?.includes(label(key)))!
}
async function open(overrides: Partial<ComponentProps<typeof FloatingComposer>> = {}) {
  await act(async () => root.render(createElement(FloatingComposer, { ...props, ...overrides })))
  await act(async () => trigger().click())
}
async function key(value: string) {
  await act(async () => document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: value, bubbles: true, cancelable: true })))
}
it('exposes modes directly and toggles the selected mode back to agent', async () => {
  const setMode = vi.fn()
  await open({ mode: 'plan', setMode })
  expect(host.querySelectorAll('[role="dialog"]')).toHaveLength(1)
  expect(action('composerModePlanFull').querySelector('[aria-label]')).not.toBeNull()
  await act(async () => action('composerModePlanFull').click())
  expect(setMode).toHaveBeenCalledWith('agent')
  expect(trigger().getAttribute('aria-expanded')).toBe('false')
  await act(async () => trigger().click())
  await act(async () => action('composerModeGoalFull').click())
  expect(setMode).toHaveBeenLastCalledWith('goal')
})
it('shows skills directly and navigates the unified list without leaving search', async () => {
  await open()
  const search = host.querySelector<HTMLInputElement>('input[role="combobox"]')!
  expect(document.activeElement).toBe(search)
  expect(host.textContent).toContain('Review changes')
  const selected = () => host.querySelector('[role="option"][aria-selected="true"]')
  expect(selected()).toBe(action('composerPlusAddFile'))
  await key('ArrowDown')
  expect(selected()).toBe(action('composerModeGoalFull'))
  await key('End')
  expect(selected()?.textContent).toContain('review')
  await key('Home')
  expect(selected()).toBe(action('composerPlusAddFile'))
  await key('Escape')
  expect(trigger().getAttribute('aria-expanded')).toBe('false')
  expect(document.activeElement).toBe(trigger())
})
it('filters all groups and selects a skill from search with Enter', async () => {
  const setInput = vi.fn()
  await open({ setInput })
  const search = host.querySelector<HTMLInputElement>('input[role="combobox"]')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(search, 'review')
    search.dispatchEvent(new Event('input', { bubbles: true }))
  })
  expect(host.querySelectorAll('[role="option"]')).toHaveLength(1)
  expect(host.querySelector('[role="option"]')?.textContent).toContain('review')
  await key('Enter')
  expect(trigger().getAttribute('aria-expanded')).toBe('false')
  expect(setInput).toHaveBeenCalledWith('')
  expect(host.textContent).toContain('review')
})
it('closes the panel when opening the file picker even if selection is cancelled', async () => {
  await open()
  await act(async () => action('composerPlusAddFile').click())
  expect(window.dsGui.pickWorkspaceFiles).toHaveBeenCalledOnce()
  expect(trigger().getAttribute('aria-expanded')).toBe('false')
})

it('preloads the menu before opening and reuses the plugin and skill cache', async () => {
  await act(async () => root.render(createElement(FloatingComposer, props)))
  const request = vi.mocked(window.dsGui.runtimeRequest)
  expect(trigger().getAttribute('aria-expanded')).toBe('false')
  for (const path of ['/v1/skills', '/v1/plugins?workspace=%2Frepo', '/v1/mcp/servers']) {
    expect(request.mock.calls.filter(([url]) => url === path)).toHaveLength(1)
  }
  await act(async () => trigger().click())
  expect(host.textContent).toContain('Review changes')
  for (const path of ['/v1/skills', '/v1/plugins?workspace=%2Frepo']) {
    expect(request.mock.calls.filter(([url]) => url === path)).toHaveLength(1)
  }
})

it('waits for the runtime and preloads again after reconnection without a click', async () => {
  const render = async (runtimeReady: boolean) => {
    await act(async () => root.render(createElement(FloatingComposer, { ...props, runtimeReady })))
  }
  const request = vi.mocked(window.dsGui.runtimeRequest)
  await render(false)
  expect(request.mock.calls.filter(([url]) => url === '/v1/skills')).toHaveLength(0)
  await render(true)
  expect(request.mock.calls.filter(([url]) => url === '/v1/skills')).toHaveLength(1)
  await render(false)
  await render(true)
  expect(request.mock.calls.filter(([url]) => url === '/v1/skills')).toHaveLength(2)
})

it('does not loop on failed plugin preload and retries when the menu is opened', async () => {
  const request = vi.mocked(window.dsGui.runtimeRequest)
  request.mockResolvedValue({ ok: false, status: 503, body: '' })
  await act(async () => root.render(createElement(FloatingComposer, props)))
  const pluginCalls = () => request.mock.calls.filter(([url]) => url.startsWith('/v1/plugins'))
  expect(pluginCalls()).toHaveLength(1)
  await act(async () => trigger().click())
  expect(pluginCalls()).toHaveLength(2)
})

it('ignores a slow plugin response from the previous workspace', async () => {
  const request = vi.mocked(window.dsGui.runtimeRequest)
  let finishOld!: (value: { ok: boolean; status: number; body: string }) => void
  request.mockImplementation(async (url) => {
    if (url === '/v1/plugins?workspace=%2Frepo') {
      return new Promise(resolve => { finishOld = resolve })
    }
    return { ok: true, status: 200, body: JSON.stringify({ plugins: [{ name: 'new-workspace-plugin' }] }) }
  })
  await act(async () => root.render(createElement(FloatingComposer, props)))
  await act(async () => { useChatStore.setState({ workspaceRoot: '/new-repo' }) })
  await act(async () => trigger().click())
  expect(host.textContent).toContain('new-workspace-plugin')
  await act(async () => finishOld({ ok: true, status: 200, body: JSON.stringify({ plugins: [{ name: 'old-workspace-plugin' }] }) }))
  expect(host.textContent).toContain('new-workspace-plugin')
  expect(host.textContent).not.toContain('old-workspace-plugin')
})
