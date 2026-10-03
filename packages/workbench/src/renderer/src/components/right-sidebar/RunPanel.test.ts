// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChatBlock } from '../../agent/types'
import { RunPanel } from './RunPanel'
import { useChatStore } from '../../store/chat-store'
import { useRunPanelStore } from '../../store/run-panel-store'

vi.mock('../../store/chat-store', async () => {
  const { create } = await import('zustand')
  return { useChatStore: create(() => ({ activeThreadId: 'thread', blocks: [] })) }
})
vi.mock('../../hooks/use-thread-tasks', () => ({
  useLiveTasks: (tasks: unknown) => tasks,
  fetchTaskDetail: vi.fn(), resumeTask: vi.fn(), resumeThreadAgent: vi.fn()
}))
vi.mock('react-i18next', async (importOriginal) => ({ ...await importOriginal<typeof import('react-i18next')>(), useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../chat/tool/primitives', async (importOriginal) => ({ ...await importOriginal<typeof import('../chat/tool/primitives')>(), ToolCopyButton: () => null }))
vi.mock('../chat/StreamdownAssistant', () => ({
  StreamdownAssistant: ({ text }: { text: string }) => createElement('p', null, text)
}))
const agent = (id: string, summary?: string): ChatBlock => ({
  kind: 'subagent', id, agentId: id, agentType: 'code', cardKind: 'delegate',
  status: summary ? 'completed' : 'running', summary, prompt: `Assignment ${id}`,
  steps: [{ id: `${id}-progress`, kind: 'progress', label: `Working on ${id}` }]
})
let root: Root
let container: HTMLDivElement
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  useChatStore.setState({ activeThreadId: 'thread', blocks: [agent('a'), agent('b')] })
  useRunPanelStore.getState().open({ threadId: 'thread', kind: 'subagent', id: 'a' })
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})
describe('run sidebar', () => {
  it('updates live blocks, switches agents, and preserves completed entries', async () => {
    await act(async () => root.render(createElement(RunPanel)))
    expect(container.textContent).toContain('Working on a')
    await act(async () => useChatStore.setState({ blocks: [agent('a', 'Finished a'), agent('b')] }))
    expect(container.textContent).toContain('Finished a')
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')!.click())
    const choices = [...container.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')]
    expect(choices.some((button) => button.textContent?.includes('Assignment a'))).toBe(true)
    await act(async () => choices.find((button) => button.textContent?.includes('Assignment b'))!.click())
    expect(container.textContent).toContain('Working on b')
    expect(container.textContent).not.toContain('Finished a')
  })
  it('never shows another conversation\'s selected run', async () => {
    await act(async () => root.render(createElement(RunPanel)))
    await act(async () => useChatStore.setState({ activeThreadId: 'other', blocks: [] }))
    expect(container.textContent).not.toContain('Working on a')
  })
  it('reopening reads progress received while the panel was closed', async () => {
    await act(async () => root.render(createElement(RunPanel)))
    await act(async () => root.render(null))
    useChatStore.setState({ blocks: [agent('a', 'Finished while closed')] })
    await act(async () => root.render(createElement(RunPanel)))
    expect(container.textContent).toContain('Finished while closed')
  })
})

it('supports keyboard task selection and Escape returns focus to the title', async () => {
  await act(async () => root.render(createElement(RunPanel)))
  const trigger = container.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')!
  await act(async () => trigger.click())
  expect(document.activeElement?.getAttribute('aria-checked')).toBe('true')
  await act(async () => document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })))
  expect(document.activeElement?.textContent).toContain('Assignment b')
  await act(async () => document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
  expect(container.querySelector('[role="menu"]')).toBeNull()
  expect(document.activeElement).toBe(trigger)
})

it('keeps long histories compact, while old progress remains expandable', async () => {
  const block = agent('a') as Extract<ChatBlock, { kind: 'subagent' }>
  block.steps = Array.from({ length: 10 }, (_, index) => ({ id: `update-${index}`, kind: 'progress', label: `Progress message ${index}` }))
  useChatStore.setState({ blocks: [block] })
  await act(async () => root.render(createElement(RunPanel)))
  expect(container.querySelector('[data-run-conversation]')).not.toBeNull()
  expect(container.querySelector('.ds-user-message-bubble')?.textContent).toBe('Assignment a')
  const process = container.querySelector<HTMLElement>('.ds-work-meta-row')!
  expect(process).not.toBeNull()
  await act(async () => process.click())
  expect(container.textContent).toContain('Progress message 0')
  expect(container.textContent).toContain('Progress message 9')
})


it('folds completed progress, including failed actions, and allows deliberate expansion', async () => {
  const block = agent('a') as Extract<ChatBlock, { kind: 'subagent' }>
  block.steps = [
    { id: 'update', kind: 'progress', label: 'Inspecting files' },
    { id: 'failed-read', kind: 'tool', label: 'Read file', toolName: 'read_file', ok: false, output: 'Access denied' }
  ]
  useChatStore.setState({ blocks: [block] })
  await act(async () => root.render(createElement(RunPanel)))
  await act(async () => useChatStore.setState({ blocks: [{ ...block, status: 'completed', summary: 'Analysis complete' }] }))
  expect(container.querySelector('.ds-chat-answer')?.textContent).toBe('Analysis complete')
  expect(container.textContent).not.toContain('Access denied')
  await act(async () => container.querySelector<HTMLElement>('.ds-work-meta-row')!.click())
  for (const button of container.querySelectorAll<HTMLButtonElement>('.ds-tool-batch__header')) {
    await act(async () => button.click())
  }
  const tool = container.querySelector<HTMLElement>('[id="block-run:a:failed-read"] [role="button"]')!
  expect(tool).not.toBeNull()
  await act(async () => tool.click())
  expect(container.textContent).toContain('Access denied')
})


it('opens the task menu on mouse hover without stealing focus', async () => {
  await act(async () => root.render(createElement(RunPanel)))
  const focusBefore = document.activeElement
  await act(async () => container.querySelector('.ds-run-switcher')!.dispatchEvent(new PointerEvent('pointerover', { bubbles: true, pointerType: 'mouse' })))
  expect(container.querySelector('[role="menu"]')).not.toBeNull()
  expect(document.activeElement).toBe(focusBefore)
  await act(async () => container.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')!.click())
  expect(container.querySelector('[role="menu"]')).not.toBeNull()
})
