// @vitest-environment happy-dom
import { act, Component, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { ApprovalBubble } from './components/chat/ApprovalBubble'
import { WecomChannelSetup } from './components/channels/WecomChannelSetup'
import { useWorkspaceEditorStore } from './store/workspace-editor-store'
import { mergePendingApprovalBlocks, mergePendingUserInputBlocks } from './store/chat-store-runtime-helpers'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const mocked = vi.hoisted(() => ({ resolveApproval: vi.fn(async () => true), openSettings: vi.fn() }))
vi.mock('./store/chat-store', () => ({ useChatStore: (selector: Function) => selector(mocked) }))
vi.mock('./lib/resolve-automation-wecom-config', () => ({
  loadWecomChannelState: async () => ({ configured: true }), saveWecomWebhookKey: vi.fn()
}))
const mounts: Array<() => void> = []
function mount() {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const el = document.createElement('div'); document.body.append(el)
  const root = createRoot(el)
  mounts.push(() => { act(() => root.unmount()); el.remove() })
  return { el, root }
}
afterEach(() => { mounts.splice(0).forEach(fn => fn()); vi.restoreAllMocks(); vi.unstubAllGlobals() })

it('reproduces approval spinner persisting after server success', async () => {
  const { el, root } = mount()
  const block = { kind: 'approval', id: 'a', approvalId: 'a', status: 'pending' }
  await act(async () => root.render(createElement(ApprovalBubble, { block } as any)))
  await act(async () => [...el.querySelectorAll('button')].find(b => b.textContent === 'approvalAllowOnce')!.click())
  await act(async () => root.render(createElement(ApprovalBubble, { block: { ...block, status: 'allowed' } } as any)))
  expect(el.querySelector('[data-state]')?.getAttribute('data-state')).toBe('approving')
})

it('reproduces a channel error object crashing rendering', async () => {
  const { root } = mount()
  const caught = vi.fn()
  class Boundary extends Component<any, { failed: boolean }> {
    state = { failed: false }
    static getDerivedStateFromError() { return { failed: true } }
    componentDidCatch(error: Error) { caught(error) }
    render() { return this.state.failed ? 'failed' : this.props.children }
  }
  vi.spyOn(console, 'error').mockImplementation(() => {})
  vi.stubGlobal('dsGui', undefined)
  window.dsGui = { runtimeRequest: async () => ({ ok: false, status: 502, body: JSON.stringify({ detail: { error: 'wecom_send_failed', message: 'bad webhook' } }) }) } as any
  await act(async () => root.render(createElement(Boundary, null, createElement(WecomChannelSetup, { runtimeReady: true, onConfigured() {} }))))
  await act(async () => [...document.querySelectorAll('button')].find(b => b.textContent === 'channelWecomTestSend')!.click())
  expect(caught.mock.calls[0][0].message).toContain('Objects are not valid as a React child')
})

function dirtyTab() {
  useWorkspaceEditorStore.setState({ tabs: [{ id: 'a.ts', path: 'a.ts', kind: 'text', content: 'first', savedContent: 'old', loading: false, error: null }] })
}
it('reproduces edits during save being incorrectly marked saved', async () => {
  dirtyTab()
  let finish!: (value: any) => void
  const write = vi.fn(() => new Promise(resolve => { finish = resolve }))
  window.dsGui = { writeWorkspaceFile: write } as any
  const pending = useWorkspaceEditorStore.getState().saveTab('a.ts', '/workspace')
  useWorkspaceEditorStore.getState().updateTabContent('a.ts', 'second')
  finish({ ok: true })
  await pending
  expect(write.mock.calls[0][0].content).toBe('first')
  expect(useWorkspaceEditorStore.getState().tabs[0].savedContent).toBe('second')
})
it('reproduces IPC save rejection without an inline error', async () => {
  dirtyTab()
  window.dsGui = { writeWorkspaceFile: async () => { throw new Error('IPC disconnected') } } as any
  await expect(useWorkspaceEditorStore.getState().saveTab('a.ts', '/workspace')).rejects.toThrow('IPC disconnected')
  expect(useWorkspaceEditorStore.getState().tabs[0].error).toBeNull()
})

it('reproduces pending approval poll failing to recover a submission error', () => {
  const result = mergePendingApprovalBlocks([{ kind: 'approval', id: 'a', approvalId: 'a', status: 'error' }] as any, [{ approvalId: 'a', summary: 'still waiting' }] as any)
  expect(result.blocks[0]).toMatchObject({ status: 'error' })
  expect(result.firstAddedBlockId).toBeNull()
})

it('reproduces pending question poll failing to recover a submission error', () => {
  const result = mergePendingUserInputBlocks([{ kind: 'user_input', id: 'q', requestId: 'q', status: 'error' }] as any, [{ requestId: 'q', questions: [] }])
  expect(result.blocks[0]).toMatchObject({ status: 'error' })
  expect(result.firstAddedBlockId).toBeNull()
})
