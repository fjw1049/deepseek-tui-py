// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { MessageTimeline } from './MessageTimeline'
import { useChatStore } from '../../store/chat-store'
vi.mock('./StreamdownAssistant', () => ({ StreamdownAssistant: ({text}: any) => createElement('p', null, text) }))
const initial = useChatStore.getState()
let host: HTMLDivElement; let root: ReturnType<typeof createRoot>
const blocks = Array.from({length: 40}, (_, i) => [{kind:'user',id:`u${i}`,text:`Question ${i}`},{kind:'assistant',id:`a${i}`,text:`Answer ${i}`}]).flat()
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  useChatStore.setState({ ...initial, activeThreadId:'audit', blocks: blocks as any, busy:false })
  Object.defineProperty(HTMLElement.prototype, 'scrollHeight', { configurable:true, get: () => 10000 })
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable:true, get: () => 600 })
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); useChatStore.setState(initial,true) })
async function render() {
  await act(async () => root.render(createElement(MessageTimeline, { blocks: blocks as any, live:'',liveReasoning:'', activeThreadId:'audit',runtimeConnection:'ready',onRetryConnection(){},onOpenSettings(){},onOpenDiagnostics(){} })))
}
it('keeps collapsed history bounded while generating', async () => {
  await render()
  expect(host.querySelectorAll('.ds-message-turn')).toHaveLength(18)
  await act(async () => useChatStore.setState({busy:true}))
  expect(host.querySelectorAll('.ds-message-turn')).toHaveLength(18)
})
it('mounts hidden history before finishing a jump', async () => {
  await render()
  expect(host.querySelector('#block-u0')).toBeNull()
  await act(async () => useChatStore.getState().scrollToBlock('u0'))
  expect(host.querySelector('#block-u0')).not.toBeNull()
  expect(useChatStore.getState().scrollToBlockId).toBeNull()
})
