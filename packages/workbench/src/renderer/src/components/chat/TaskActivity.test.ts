// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { TaskActivity } from './TaskActivity'
import type { DockSubagentItem } from '../../lib/extract-subagents-from-blocks'
import common from '../../locales/zh/common.json'

vi.mock('react-i18next', () => ({ useTranslation: () => ({
  t: (key: string, values: Record<string, unknown> = {}) =>
    String(common[key as keyof typeof common] || key).replace(/\{\{(\w+)\}\}/g, (_, name) => String(values[name]))
}) }))

let root: Root
let container: HTMLDivElement
const onOpen = vi.fn()
const agent = (id: string, status: DockSubagentItem['status'] = 'running'): DockSubagentItem => ({
  id, agentId: id, agentType: 'code', prompt: `检查 ${id} 的界面布局`, status
})
const render = async (agents: DockSubagentItem[], tasks: Parameters<typeof TaskActivity>[0]['tasks'] = []): Promise<void> => {
  await act(async () => root.render(createElement(TaskActivity, { agents, tasks, onOpen })))
}
const trigger = (): HTMLButtonElement => container.querySelector('.ds-task-activity-trigger')!

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  onOpen.mockClear()
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

it('opens a single run directly and stops its activity indicator on completion', async () => {
  await render([agent('a')])
  expect(trigger().textContent).toContain('检查 a 的界面布局')
  expect(trigger().getAttribute('aria-expanded')).toBeNull()
  await act(async () => trigger().click())
  expect(onOpen).toHaveBeenCalledWith({ kind: 'subagent', id: 'a' })
  await render([agent('a', 'completed')])
  expect(trigger().textContent).toContain('已完成')
  expect(container.querySelector('.ds-task-activity-orbit')).toBeNull()
  await render([], [{ id: 'task-a', prompt: '检查后台任务', status: 'queued' }])
  await act(async () => trigger().click())
  expect(onOpen).toHaveBeenLastCalledWith({ kind: 'task', id: 'task-a' })
})

it('counts running work separately from queued work and keeps failures visible', async () => {
  await render([agent('a'), agent('b', 'pending'), agent('c', 'failed')], [
    { id: 't', prompt: '等待执行', status: 'queued' }
  ])
  expect(container.querySelector('[role="status"]')?.textContent).toBe('1 项运行中')
  expect(trigger().textContent).toContain('1 项失败')
  expect(trigger().getAttribute('aria-expanded')).toBe('false')
  expect(container.querySelector('.ds-task-activity-body')?.hasAttribute('inert')).toBe(true)
  await act(async () => trigger().click())
  const rows = [...container.querySelectorAll<HTMLButtonElement>('.ds-task-activity-row')]
  expect(rows[0].textContent).toContain('排队中')
  expect(rows[2].textContent).toContain('排队中')
  await act(async () => rows[2].click())
  expect(onOpen).toHaveBeenCalledWith({ kind: 'subagent', id: 'b' })
})

it('preserves disclosure and row order when runs finish or more work arrives', async () => {
  await render([agent('a'), agent('b')])
  await act(async () => trigger().click())
  await render([agent('a', 'completed'), agent('b', 'completed')])
  expect(trigger().getAttribute('aria-expanded')).toBe('true')
  expect(container.querySelector('[role="status"]')?.textContent).toBe('2 项已完成')
  expect([...container.querySelectorAll('.ds-task-activity-row .ds-task-activity-title')].map((row) => row.textContent))
    .toEqual(['检查 a 的界面布局', '检查 b 的界面布局'])
  await act(async () => trigger().click())
  await render([agent('a', 'completed'), agent('b', 'completed'), agent('c')])
  expect(trigger().getAttribute('aria-expanded')).toBe('false')
  await render([])
  expect(trigger().disabled).toBe(true)
  expect(trigger().textContent).toContain('暂无任务')
})
