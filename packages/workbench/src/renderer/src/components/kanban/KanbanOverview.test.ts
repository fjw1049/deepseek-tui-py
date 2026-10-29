// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { KanbanOverview } from './KanbanOverview'
import type { KanbanBoard, KanbanCard, KanbanProjectBoard } from './kanban.logic'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../../i18n', () => ({ default: { t: (key: string) => key } }))

const project = (i: number): KanbanProjectBoard => {
  const card: KanbanCard = {
    cardId: `c${i}`, threadId: `t${i}`, projectId: `p${i}`, column: 'done', title: `task ${i}`,
    branch: null, timestamp: null, sortTimestamp: 0, draftPrompt: ''
  }
  return { projectId: `p${i}`, projectName: `project-${i}`, workspacePath: `/p${i}`, draft: [], inProgress: [], done: [card], totalCount: 1 }
}
const board: KanbanBoard = { projects: Array.from({ length: 100 }, (_, i) => project(i)), totalCount: 100 }
let host: HTMLDivElement, root: Root
let clientWidth = 0

beforeEach(() => {
  ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => clientWidth })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  clientWidth = 0
})

const render = (): Promise<void> => act(async () => root.render(createElement(KanbanOverview, {
  board, onOpenProject() {}, onOpenCard() {}, onNewTask() {}
})))
const names = (): string[] => [...host.querySelectorAll('section h2')].map((node) => node.textContent ?? '')

it('mounts only the columns near the horizontal viewport', async () => {
  clientWidth = 1360 // four 21.25rem columns at 16px
  await render()
  expect(names()).toEqual(['project-0', 'project-1', 'project-2', 'project-3', 'project-4', 'project-5', 'project-6'])
  const scroller = host.firstElementChild as HTMLDivElement
  scroller.scrollLeft = 50 * 340
  await act(async () => {
    scroller.dispatchEvent(new Event('scroll'))
    await new Promise((resolve) => requestAnimationFrame(resolve))
  })
  expect(names()[0]).toBe('project-46') // project-49 still peeks in past the 2rem edge padding
  expect(names()).toContain('project-50')
  expect(names()).not.toContain('project-0')
})

it('renders every column when there is no layout to measure', async () => {
  await render()
  expect(names()).toHaveLength(100)
})
