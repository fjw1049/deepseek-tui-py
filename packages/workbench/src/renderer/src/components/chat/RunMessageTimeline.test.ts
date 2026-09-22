// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { RunMessageTimeline } from './MessageTimeline'
import { useChatStore } from '../../store/chat-store'
import type { ChatBlock } from '../../agent/types'
import { useDisclosureStore } from './model/disclosure-store'

vi.mock('./StreamdownAssistant', () => ({
  StreamdownAssistant: ({ text }: { text: string }) => createElement('p', null, text)
}))
const initial = useChatStore.getState()
let container: HTMLDivElement
let root: ReturnType<typeof createRoot>
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
  useDisclosureStore.setState({ disclosureById: {} })
  useChatStore.setState({ busy: true, activeThreadId: 'main', workspaceRoot: '/main', blocks: [
    { kind: 'approval', id: 'approval', approvalId: 'approval', toolCallId: 'run:tool', summary: 'MAIN APPROVAL', status: 'pending' }
  ] })
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  useChatStore.setState(initial, true)
})
const blocks: ChatBlock[] = [
  { kind: 'user', id: 'run:user', text: 'RUN ASSIGNMENT' },
  { kind: 'assistant', id: 'run:preface', text: 'Inspect files', agentSegment: 'mid_turn_preface' },
  { kind: 'tool', id: 'run:tool', summary: 'read_file', status: 'success', detail: 'FULL TOOL OUTPUT', meta: { tool_name: 'read_file', tool_input: { path: '/run/file.ts' } } },
  { kind: 'assistant', id: 'run:answer', text: 'FINAL ANSWER', agentSegment: 'final_answer' }
]
it('uses main conversation disclosure and tool cards without main-thread actions or gates', async () => {
  await act(async () => root.render(createElement(RunMessageTimeline, { blocks, workspace: '/run', active: false })))
  expect(container.querySelector('.ds-user-message-bubble')?.textContent).toBe('RUN ASSIGNMENT')
  expect(container.querySelector('.ds-chat-answer')?.textContent).toBe('FINAL ANSWER')
  expect(container.querySelector('.ds-rewind-trigger')).toBeNull()
  expect(container.textContent).not.toContain('MAIN APPROVAL')
  expect(container.textContent).not.toContain('FULL TOOL OUTPUT')
  await act(async () => (container.querySelector('.ds-work-meta-row') as HTMLElement).click())
  // The shared process renderer may also group successful calls into a disclosure.
  for (const button of container.querySelectorAll<HTMLButtonElement>('.ds-work-summary > button')) {
    await act(async () => button.click())
  }
  for (const button of container.querySelectorAll<HTMLButtonElement>('.ds-tool-batch__header')) {
    await act(async () => button.click())
  }
  const tool = container.querySelector('#block-run\\:tool [role="button"]') as HTMLElement
  expect(tool).not.toBeNull()
  await act(async () => tool.click())
  expect(container.textContent).toContain('FULL TOOL OUTPUT')
})
it('replaces the live answer once and ignores main busy state when settled', async () => {
  const live = [...blocks.slice(0, -1), { ...blocks[3]!, text: 'LIVE ANSWER' }] as ChatBlock[]
  await act(async () => root.render(createElement(RunMessageTimeline, { blocks: live, liveId: 'run:answer', workspace: '/run', active: true })))
  expect(container.textContent?.match(/LIVE ANSWER/g)).toHaveLength(1)
  await act(async () => root.render(createElement(RunMessageTimeline, { blocks, liveId: null, workspace: '/run', active: false })))
  expect(container.textContent).not.toContain('LIVE ANSWER')
  expect(container.textContent?.match(/FINAL ANSWER/g)).toHaveLength(1)
})
