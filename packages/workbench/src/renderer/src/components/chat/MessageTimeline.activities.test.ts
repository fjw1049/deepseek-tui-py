// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MessageTimeline } from './MessageTimeline'
import { useChatStore } from '../../store/chat-store'
import { useRunPanelStore } from '../../store/run-panel-store'
import { extractSubagentsFromBlocks } from '../../lib/extract-subagents-from-blocks'
import { extractTasksFromBlocks } from '../../lib/extract-tasks-from-blocks'
import type { ChatBlock } from '../../agent/types'

vi.mock('./StreamdownAssistant', () => ({
  StreamdownAssistant: ({ text }: { text: string }) => createElement('p', null, text)
}))

const initial = useChatStore.getState()
const initialPanel = useRunPanelStore.getState()
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
  useRunPanelStore.setState(initialPanel, true)
  vi.unstubAllGlobals()
})

async function render(blocks: ChatBlock[], busy = true): Promise<void> {
  act(() => useChatStore.setState({ busy, blocks, activeThreadId: 'activities', workspaceRoot: '' }))
  await act(async () => root.render(createElement(MessageTimeline, {
    blocks, live: '', liveReasoning: '', activeThreadId: 'activities', runtimeConnection: 'ready',
    onRetryConnection: () => {}, onOpenSettings: () => {}, onOpenDiagnostics: () => {}
  })))
}

function checklist(done: number): ChatBlock {
  return { kind: 'tool', id: `plan-${done}`, toolKind: 'tool_call', status: 'success', summary: 'checklist',
    meta: { tool_name: 'checklist', task_updates: { checklist: { items: Array.from({ length: 4 }, (_, i) => ({
      id: String(i), content: `步骤 ${i + 1}`, status: i < done ? 'completed' : i === done ? 'in_progress' : 'pending'
    })) } } } }
}

const agent = (id: string, status: 'running' | 'completed' | 'failed'): ChatBlock => ({
  kind: 'subagent', id, cardKind: 'delegate', agentId: id, agentType: 'research',
  prompt: `分析 ${id}`, status
})

it.each([2, 4])('shows a collapsed top summary only after the turn ends with %i completed tasks', async (done) => {
  const blocks: ChatBlock[] = [{ kind: 'user', id: 'user', text: 'mock four todos' }, checklist(0)]
  await render(blocks)
  expect(container.querySelector('.ds-inline-todo')).toBeNull()
  blocks.push(checklist(done))
  await render([...blocks])
  expect(container.querySelector('.ds-inline-todo')).toBeNull()
  await act(async () => (container.querySelector('.ds-work-meta-row') as HTMLButtonElement).click())
  expect(container.querySelector('.ds-inline-todo')).toBeNull()
  await render([...blocks], false)
  const card = container.querySelector('.ds-inline-todo')!
  expect(card).not.toBeNull()
  expect(card.textContent).toContain(`${done}/4`)
  expect(card.querySelector('button')?.getAttribute('aria-expanded')).toBe('false')
  expect(card.querySelector('ul')).toBeNull()
  const order = Array.from(container.querySelectorAll('.ds-inline-todo, .ds-work-meta-row'))
  expect(order[0]).toBe(card)
  await act(async () => card.querySelector('button')!.click())
  expect(card.querySelectorAll('li')).toHaveLength(4)
  expect(card.querySelectorAll('[data-status="completed"]')).toHaveLength(done)
  await act(async () => (container.querySelector('.ds-work-meta-row') as HTMLButtonElement).click())
  expect(container.querySelector('.ds-inline-todo')).toBe(card)
  expect(card.querySelector('button')?.getAttribute('aria-expanded')).toBe('true')
})

it('leaves subagent status in the side card without duplicate timeline entries', async () => {
  const blocks: ChatBlock[] = [
    agent('A', 'failed'), agent('B', 'running'),
    { kind: 'tool', id: 'wait', summary: 'agent: wait', toolKind: 'tool_call', status: 'success',
      detail: 'raw wait log', meta: { tool_name: 'agent' } }
  ]
  await render(blocks)
  expect(container.querySelector('.ds-subagent-summary')).toBeNull()
  expect(container.querySelector('#block-wait')).toBeNull()
  expect(extractSubagentsFromBlocks(useChatStore.getState().blocks).map(({ agentId, status }) => ({ agentId, status })))
    .toEqual([{ agentId: 'A', status: 'failed' }, { agentId: 'B', status: 'running' }])
  await act(async () => (container.querySelector('.ds-work-meta-row') as HTMLButtonElement).click())
  expect(container.querySelector('.ds-subagent-summary')).toBeNull()
  expect(container.querySelector('.ds-subagent-bubble')).toBeNull()
  await render([agent('A', 'completed'), agent('B', 'completed')])
  expect(container.querySelector('.ds-subagent-summary')).toBeNull()
  expect(useChatStore.getState().busy).toBe(true)
})

it('omits a single agent after reload and keeps failed tool logs in details', async () => {
  await render([
    agent('A', 'completed'),
    { kind: 'tool', id: 'failed', summary: 'agent_resume: failed', status: 'error',
      toolKind: 'tool_call', meta: { tool_name: 'agent_resume' } }
  ], false)
  expect(container.querySelector('.ds-subagent-summary')).toBeNull()
  expect(container.querySelector('#block-failed')).toBeNull()
  await act(async () => (container.querySelector('.ds-work-meta-row') as HTMLButtonElement).click())
  expect(container.querySelector('#block-failed [aria-label="error"]')).not.toBeNull()
})

it('appends progress while running and preserves the full history in completed details', async () => {
  const blocks: ChatBlock[] = [
    { kind: 'assistant', id: 'p1', text: '旧进展', agentSegment: 'mid_turn_preface' },
    { kind: 'tool', id: 'fetch', summary: 'fetch_url', toolKind: 'tool_call', status: 'success', detail: 'Fetched page content' },
    { kind: 'reasoning', id: 'r', text: 'raw reasoning', narration: '较新进展' },
    { kind: 'tool', id: 'clone', summary: 'exec_shell', toolKind: 'command_execution', status: 'error', detail: 'Clone failed' },
    { kind: 'assistant', id: 'p2', text: '最新进展', agentSegment: 'mid_turn_preface' }
  ]
  await render(blocks.slice(0, 1))
  expect(container.textContent).toContain('旧进展')
  await render(blocks)
  const details = container.querySelector('.ds-work-meta-row') as HTMLButtonElement
  if (details.getAttribute('aria-expanded') === 'true') await act(async () => details.click())
  expect(container.textContent).toContain('最新进展')
  expect(container.textContent).toContain('旧进展')
  expect(container.textContent).toContain('较新进展')
  expect(container.textContent!.indexOf('旧进展')).toBeLessThan(container.textContent!.indexOf('较新进展'))
  expect(container.textContent!.indexOf('较新进展')).toBeLessThan(container.textContent!.indexOf('最新进展'))
  const processRows = Array.from(container.querySelectorAll('.ds-process-narration, .ds-tool-batch, #block-clone'))
    .map(node => node.classList.contains('ds-tool-batch') ? 'tool-batch' : node.id || node.textContent)
  expect(processRows).toEqual(['旧进展', 'tool-batch', '较新进展', 'block-clone', '最新进展'])
  expect(container.textContent).not.toContain('Fetched page content')
  expect(container.textContent).not.toContain('Clone failed')
  await render([...blocks, { kind: 'assistant', id: 'answer', text: '最终交付', agentSegment: 'final_answer' }], false)
  expect(container.textContent).toContain('最终交付')
  expect(container.textContent).not.toContain('最新进展')
  await act(async () => details.click())
  expect(container.textContent).toContain('旧进展')
  expect(container.textContent).toContain('最新进展')
})

it.each(['success', 'error'] as const)('keeps a %s tool waiting for approval visible even when it is checklist or orchestration', async status => {
  for (const toolName of ['checklist', 'agent']) {
    await render([
      checklist(0), agent('A', 'running'),
      { kind: 'tool', id: 'waiting', summary: toolName, status, toolKind: 'tool_call', meta: { tool_name: toolName } },
      { kind: 'approval', id: 'approval', approvalId: 'waiting', summary: 'Please approve', status: 'pending' }
    ])
    const details = container.querySelector('.ds-work-meta-row') as HTMLButtonElement
    if (details.getAttribute('aria-expanded') === 'true') await act(async () => details.click())
    expect(container.querySelector('#block-waiting')).not.toBeNull()
  }
})

it('keeps completed parent narration folded while its child continues running', async () => {
  await render([
    { kind: 'assistant', id: 'p', text: '等待子代理', agentSegment: 'mid_turn_preface' },
    agent('A', 'running'),
    { kind: 'assistant', id: 'answer', text: '已交付当前结果', agentSegment: 'final_answer' }
  ], false)
  expect(container.textContent).not.toContain('等待子代理')
  expect(container.textContent).toContain('已交付当前结果')
  expect(extractSubagentsFromBlocks(useChatStore.getState().blocks)[0].status).toBe('running')
})

it.each(['queued', 'running', 'completed', 'failed'] as const)(
  'keeps %s tasks available to the side card without duplicate timeline entries', async (status) => {
    const tasks = [{ id: 'task-A', prompt: '审核后台任务', status }]
    await render([
      { kind: 'tool', id: 'create-task', toolKind: 'tool_call', summary: 'task_create', status: 'success',
        meta: { tool_name: 'task_create', tasks } },
      { kind: 'assistant', id: 'answer', text: '任务已派发。', agentSegment: 'final_answer' }
    ], status === 'queued' || status === 'running')
    expect(container.querySelector('.ds-task-activity')).toBeNull()
    expect(container.querySelector('#block-create-task')).toBeNull()
    expect(container.textContent).toContain('任务已派发。')
    expect(extractTasksFromBlocks(useChatStore.getState().blocks)).toEqual(tasks)
    await act(async () => (container.querySelector('.ds-work-meta-row') as HTMLButtonElement).click())
    expect(container.querySelector('.ds-task-activity')).toBeNull()
  }
)

it('folds historical checklist and agent failures once the plan and agents finish', async () => {
  const failures: ChatBlock[] = ['checklist', 'agent_send_input', 'agent_send_input', 'agent_spawn', 'agent_spawn'].map((name, i) => ({
    kind: 'tool', id: `historical-error-${i}`, summary: name, status: 'error', toolKind: 'tool_call',
    detail: `Historical failure ${i}`, meta: { tool_name: name }
  }))
  await render([
    ...failures, checklist(4), agent('A', 'completed'), agent('B', 'completed'),
    { kind: 'assistant', id: 'final', text: '两个子代理已完成分析。', agentSegment: 'final_answer' }
  ], false)
  for (const block of failures) expect(container.querySelector(`#block-${block.id}`)).toBeNull()
  expect(container.querySelector('.ds-inline-todo')?.textContent).toContain('4/4')
  expect(container.querySelector('.ds-subagent-summary')).toBeNull()
  expect(container.textContent).toContain('两个子代理已完成分析。')
  await act(async () => (container.querySelector('.ds-work-meta-row') as HTMLButtonElement).click())
  expect(container.querySelector('#block-historical-error-1')).toBeNull()
  await act(async () => container.querySelector<HTMLButtonElement>('.ds-work-summary > button')!.click())
  for (const block of failures) expect(container.querySelector(`#block-${block.id}`)).not.toBeNull()
})
