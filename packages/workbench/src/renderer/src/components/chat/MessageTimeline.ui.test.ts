// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { MessageTimeline } from './MessageTimeline'
import { useChatStore } from '../../store/chat-store'
import type { ChatBlock } from '../../agent/types'

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
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  useChatStore.setState(initial, true)
})

it('folds completed progress and tool errors while preserving their details', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  document.body.append(container)
  const progress = '已确认消息没有丢失。\n\n接下来检查折叠规则。'
  const command = 'npm run verify-display'
  const blocks: ChatBlock[] = [
    { kind: 'assistant', id: 'progress', text: progress, agentSegment: 'mid_turn_preface' },
    { kind: 'tool', id: 'command', toolKind: 'command_execution', status: 'running',
      summary: `exec_shell: ${command}`, meta: { tool_name: 'exec_shell', tool_input: { command } } }
  ]
  const render = async (rows: ChatBlock[]): Promise<void> => {
    await act(async () => {
      root.render(createElement(MessageTimeline, {
        blocks: rows, liveReasoning: '', live: '', activeThreadId: 'review',
        runtimeConnection: 'ready', onRetryConnection: () => {},
        onOpenSettings: () => {}, onOpenDiagnostics: () => {}
      }))
    })
  }
  act(() => useChatStore.setState({ busy: true, blocks, workspaceRoot: '', activeThreadId: 'review' }))
  await render(blocks)
  expect(container.textContent).toContain(progress)
  expect(container.textContent).not.toContain(command)
  const commandRow = container.querySelector('#block-command [role="button"]') as HTMLElement
  await act(async () => commandRow.click())
  expect(container.querySelector('#block-command pre')?.textContent).toBe(command)

  const completed: ChatBlock[] = [
    blocks[0], { ...blocks[1], status: 'success' } as ChatBlock,
    { kind: 'tool', id: 'failed', toolKind: 'command_execution', status: 'error',
      summary: 'exec_shell: failed', detail: 'Verification could not complete',
      meta: { tool_name: 'exec_shell', tool_input: { command: 'failed' } } },
    { kind: 'assistant', id: 'answer', text: '这里是最终结果。', agentSegment: 'final_answer' }
  ]
  act(() => useChatStore.setState({ busy: false, blocks: completed }))
  await render(completed)
  expect(container.textContent).not.toContain(progress)
  expect(container.textContent).toContain('这里是最终结果。')
  expect(container.textContent).not.toContain('Verification could not complete')
  expect(container.querySelector('#block-failed')).toBeNull()
  expect(container.querySelector('#block-command')).toBeNull()
  const details = container.querySelector('.ds-work-meta-row') as HTMLButtonElement
  expect(details.getAttribute('aria-expanded')).toBe('false')
  await act(async () => details.click())
  const activity = container.querySelector('.ds-work-summary > button') as HTMLButtonElement
  if (activity) await act(async () => activity.click())
  expect(container.querySelector('#block-command')).not.toBeNull()
  expect(container.textContent).not.toContain('Verification could not complete')
  const failedRow = container.querySelector('#block-failed [role="button"]') as HTMLElement
  await act(async () => failedRow.click())
  expect(container.textContent).toContain('Verification could not complete')
  expect(container.textContent).toContain(progress)
})


it('keeps silent edit rounds compact and inserts delayed narration once without losing details', async () => {
  const blocks: ChatBlock[] = [
    { kind: 'assistant', id: 'progress', text: '已找到问题，正在修复。', agentSegment: 'mid_turn_preface' },
    ...[0, 1, 2].flatMap((i): ChatBlock[] => [
      { kind: 'assistant', id: `intent-${i}`, text: '', agentSegment: 'mid_turn_preface',
        processIntent: { scope: 'pre_tool', source: 'none', anchors: ['src/app.py'], toolCount: 1 } },
      { kind: 'reasoning', id: `reason-${i}`, text: 'private execution detail' },
      { kind: 'tool', id: `edit-${i}`, toolKind: 'file_change', status: i === 1 ? 'error' : 'running',
        summary: 'edit_file: src/app.py', detail: 'raw edit result', meta: { tool_name: 'edit_file' } }
    ])
  ]
  const render = async (): Promise<void> => {
    await act(async () => root.render(createElement(MessageTimeline, {
      blocks, liveReasoning: '', live: '', activeThreadId: 'silent-review',
      runtimeConnection: 'ready', onRetryConnection: () => {},
      onOpenSettings: () => {}, onOpenDiagnostics: () => {}
    })))
  }
  act(() => useChatStore.setState({ busy: true, blocks, workspaceRoot: '', activeThreadId: 'silent-review' }))
  await render()
  await act(async () => (container.querySelector('.ds-work-meta-row') as HTMLButtonElement).click())
  expect(container.querySelector('#block-edit-1')).toBeNull()
  expect(container.textContent).not.toContain('raw edit result')
  expect(container.querySelectorAll('.ds-process-narration')).toHaveLength(1)
  const details = container.querySelector('.ds-work-meta-row') as HTMLButtonElement
  await act(async () => details.click())
  await act(async () => details.click())
  act(() => useChatStore.setState({ busy: false }))
  await render()
  expect(details.getAttribute('aria-expanded')).toBe('true')
  expect(container.querySelector('#block-edit-1')).toBeNull()
  await act(async () => container.querySelector<HTMLButtonElement>('.ds-work-summary > button')!.click())
  expect(container.querySelector('#block-edit-1')).not.toBeNull()
  const intent = blocks[4]
  if (intent.kind === 'assistant') intent.text = '修复已完成，开始核对结果。'
  // Replace the array so the timeline rebuilds the same persisted frame.
  await act(async () => root.render(createElement(MessageTimeline, {
    blocks: [...blocks], liveReasoning: '', live: '', activeThreadId: 'silent-review',
    runtimeConnection: 'ready', onRetryConnection: () => {},
    onOpenSettings: () => {}, onOpenDiagnostics: () => {}
  })))
  expect(container.textContent?.split('修复已完成，开始核对结果。')).toHaveLength(2)
  expect(container.textContent).not.toContain('正在处理')
})


it.each([undefined, '已核对触发条件。'])('hides the first thought in collapsed history (narration: %s)', async (narration) => {
  const blocks: ChatBlock[] = [
    { kind: 'reasoning', id: 'first-thought', text: 'Initial analysis', narration },
    { kind: 'assistant', id: 'opening', text: '我先核对重复出现的条件，再验证修复。', agentSegment: 'mid_turn_preface' },
    ...Array.from({ length: 8 }, (_, i): ChatBlock => ({
      kind: 'tool', id: `tool-${i}`, summary: 'edit_file', toolKind: 'file_change', status: 'success'
    })),
    { kind: 'assistant', id: 'final', text: '修复验证完成。', agentSegment: 'final_answer' }
  ]
  act(() => useChatStore.setState({ busy: false, blocks, workspaceRoot: '', activeThreadId: 'opening-review' }))
  await act(async () => root.render(createElement(MessageTimeline, {
    blocks, liveReasoning: '', live: '', activeThreadId: 'opening-review', runtimeConnection: 'ready',
    onRetryConnection: () => {}, onOpenSettings: () => {}, onOpenDiagnostics: () => {}
  })))
  const thought = container.querySelector('.ds-process-reasoning') as HTMLElement
  expect(thought).toBeNull()
  expect(container.textContent).not.toContain('我先核对重复出现的条件')
  expect(container.textContent).not.toContain('Initial analysis')
  await act(async () => (container.querySelector('.ds-work-meta-row') as HTMLButtonElement).click())
  expect(container.querySelectorAll('.ds-process-reasoning')).toHaveLength(1)
  expect(container.querySelectorAll('.ds-work-summary')).toHaveLength(1)
  expect(container.querySelectorAll('.ds-process-narration')).toHaveLength(narration ? 2 : 1)
})

it('folds failed web fetches together with successful calls during retries', async () => {
  const blocks: ChatBlock[] = [
    { kind: 'assistant', id: 'preface', text: '再补齐两个小型目录。', agentSegment: 'mid_turn_preface' },
    ...(['error', 'success', 'error'] as const).map((status, i): ChatBlock => ({
      kind: 'tool', id: `fetch-${i}`, toolKind: 'tool_call', status,
      summary: 'fetch_url', detail: status === 'error' ? `Fetch failed ${i}` : 'Page content',
      meta: { tool_name: 'fetch_url', tool_input: { url: `https://example.com/${i}` } }
    })),
    { kind: 'reasoning', id: 'retry-thought', text: 'Retry with another host.' },
    { kind: 'assistant', id: 'retry', text: '两个文件抓取失败，换 CDN 重试。', agentSegment: 'mid_turn_preface' }
  ]
  act(() => useChatStore.setState({ busy: true, blocks, activeThreadId: 'retry-review', workspaceRoot: '' }))
  await act(async () => root.render(createElement(MessageTimeline, {
    blocks, live: '', liveReasoning: '', activeThreadId: 'retry-review', runtimeConnection: 'ready',
    onRetryConnection: () => {}, onOpenSettings: () => {}, onOpenDiagnostics: () => {}
  })))
  const details = container.querySelector<HTMLButtonElement>('.ds-work-meta-row')!
  if (details.getAttribute('aria-expanded') !== 'true') await act(async () => details.click())
  expect(container.querySelectorAll('.ds-tool-batch')).toHaveLength(1)
  for (let i = 0; i < 3; i++) expect(container.querySelector(`#block-fetch-${i}`)).toBeNull()
  expect(container.textContent).toContain('两个文件抓取失败，换 CDN 重试。')
  await act(async () => container.querySelector<HTMLButtonElement>('.ds-tool-batch__header')!.click())
  expect(container.querySelectorAll('[aria-label="error"]')).toHaveLength(2)
  await act(async () => container.querySelector<HTMLElement>('#block-fetch-0 [role="button"]')!.click())
  expect(container.textContent).toContain('Fetch failed 0')
})
