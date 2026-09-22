// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { KanbanProjectBoardView } from './KanbanProjectBoardView'
import type { KanbanCard, KanbanProjectBoard } from './kanban.logic'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../../i18n', () => ({ default: { t: (key: string) => key } }))

const card = (id: string, column: KanbanCard['column']): KanbanCard => ({
  cardId: id, threadId: id, projectId: '/repo', column, title: id,
  branch: null, timestamp: null, sortTimestamp: 0, draftPrompt: ''
})
const board: KanbanProjectBoard = {
  projectId: '/repo', projectName: 'repo', workspacePath: '/repo',
  draft: [card('draft', 'draft')], inProgress: [],
  done: [card('first', 'done'), card('second', 'done'), card('third', 'done')], totalCount: 4
}
let host: HTMLDivElement, root: Root
const onOpenCard = vi.fn(), onReorderColumn = vi.fn(), onDispatchDraft = vi.fn()

beforeEach(async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  // Real dnd-kit sensors and measurements; supply geometry because happy-dom has no layout.
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    if (this.style.position === 'fixed' && this.classList.contains('ds-no-drag')) {
      const scale = Number(document.documentElement.style.getPropertyValue('--ds-ui-scale')) || 1
      const delta = /translate3d\(([-\d.]+)px, ([-\d.]+)px/.exec(this.style.transform)
      return new DOMRect(
        (parseFloat(this.style.left) + Number(delta?.[1] ?? 0)) * scale,
        (parseFloat(this.style.top) + Number(delta?.[2] ?? 0)) * scale,
        parseFloat(this.style.width) * scale, parseFloat(this.style.height) * scale
      )
    }
    const section = this.closest('section')
    const column = section ? [...host.querySelectorAll('section')].indexOf(section) : 0
    const items = section ? [...section.querySelectorAll('[role="button"]')] : []
    const row = Math.max(0, items.indexOf(this))
    return new DOMRect(40 + column * 340, 180 + row * 90, 316, this.tagName === 'UL' ? 500 : 80)
  })
  await act(async () => root.render(createElement(KanbanProjectBoardView, {
    board, onOpenCard, onReorderColumn, onDispatchDraft, onNewTask: () => {}
  })))
})

afterEach(async () => {
  await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true })))
  await act(async () => root.unmount())
  // PointerSensor removes its document click guard 50 ms after finishing.
  await new Promise((resolve) => setTimeout(resolve, 60))
  host.remove()
  document.documentElement.style.removeProperty('--ds-ui-scale')
  vi.restoreAllMocks()
})

async function pointer(target: EventTarget, type: string, x: number, y: number): Promise<void> {
  await act(async () => {
    target.dispatchEvent(new PointerEvent(type, {
      bubbles: true, isPrimary: true, button: 0, clientX: x, clientY: y, pointerId: 1
    }))
  })
}

async function startDrag(): Promise<void> {
  const source = host.querySelectorAll<HTMLElement>('[role="button"]')[2]
  await pointer(source.firstElementChild!, 'pointerdown', 750, 300)
  await pointer(document, 'pointermove', 760, 300)
  await pointer(document, 'pointermove', 770, 310)
}

it.each([0.88, 1, 1.25])('preserves the source position and size at UI scale %s', async (scale) => {
  document.documentElement.style.setProperty('--ds-ui-scale', String(scale))
  await startDrag()
  const overlay = document.querySelector<HTMLElement>('.ds-no-drag[style*="position: fixed"]')!
  expect(overlay).not.toBeNull()
  expect(parseFloat(overlay.style.left) * scale).toBeCloseTo(720)
  expect(parseFloat(overlay.style.top) * scale).toBeCloseTo(270)
  expect(parseFloat(overlay.style.width) * scale).toBeCloseTo(316)
  expect(parseFloat(overlay.style.height) * scale).toBeCloseTo(80)
  const delta = /translate3d\(([-\d.]+)px, ([-\d.]+)px/.exec(overlay.style.transform)!
  expect(Number(delta[1]) * scale).toBeCloseTo(20, 0)
  expect(Number(delta[2]) * scale).toBeCloseTo(10, 0)
  expect(overlay.firstElementChild?.tagName).toBe('DIV')
  await pointer(document, 'pointerup', 770, 310)
  expect(onOpenCard).not.toHaveBeenCalled()
})

it('does not treat a click or tiny movement as a drag', async () => {
  const source = host.querySelector<HTMLElement>('[role="button"]')!
  await pointer(source, 'pointerdown', 70, 200)
  await pointer(document, 'pointermove', 73, 202)
  await pointer(document, 'pointerup', 73, 202)
  await act(async () => source.click())
  expect(document.querySelector('.ds-no-drag[style*="position: fixed"]')).toBeNull()
  expect(onOpenCard).toHaveBeenCalledWith(board.draft[0])
  expect(onDispatchDraft).not.toHaveBeenCalled()
})

it('cancels a drop outside the columns instead of snapping to a nearby card', async () => {
  await startDrag()
  await pointer(document, 'pointermove', 1100, 80)
  await pointer(document, 'pointerup', 1100, 80)
  expect(onReorderColumn).not.toHaveBeenCalled()
  expect(onDispatchDraft).not.toHaveBeenCalled()
})

it('only dispatches a draft when the pointer is inside In Progress', async () => {
  const source = host.querySelector<HTMLElement>('[role="button"]')!
  await pointer(source, 'pointerdown', 70, 200)
  await pointer(document, 'pointermove', 80, 200)
  await pointer(document, 'pointermove', 500, 160)
  await pointer(document, 'pointerup', 500, 160)
  expect(onDispatchDraft).not.toHaveBeenCalled()
})

it('dispatches a draft dropped inside In Progress', async () => {
  const source = host.querySelector<HTMLElement>('[role="button"]')!
  await pointer(source, 'pointerdown', 70, 200)
  await pointer(document, 'pointermove', 80, 200)
  await pointer(document, 'pointermove', 500, 220)
  await pointer(document, 'pointerup', 500, 220)
  expect(onDispatchDraft).toHaveBeenCalledExactlyOnceWith(board.draft[0])
  expect(onReorderColumn).not.toHaveBeenCalled()
})

it('cancels with Escape and restores normal clicks', async () => {
  await startDrag()
  await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true })))
  expect(document.querySelector('.ds-no-drag[style*="position: fixed"]')).toBeNull()
  expect(document.documentElement.classList.contains('ds-light-dismiss-active')).toBe(false)
  expect(onReorderColumn).not.toHaveBeenCalled()
  expect(onDispatchDraft).not.toHaveBeenCalled()
  await new Promise((resolve) => setTimeout(resolve, 60))
  await act(async () => host.querySelector<HTMLElement>('[role="button"]')!.click())
  expect(onOpenCard).toHaveBeenCalledWith(board.draft[0])
})

it.each([0.88, 1, 1.25])('reorders with an aligned insertion gap at UI scale %s without opening the card', async (scale) => {
  document.documentElement.style.setProperty('--ds-ui-scale', String(scale))
  await startDrag()
  await pointer(document, 'pointermove', 750, 390)
  const displaced = host.querySelectorAll<HTMLElement>('[role="button"]')[3]
  const delta = /translate3d\(([-\d.]+)px, ([-\d.]+)px/.exec(displaced.style.transform)
  expect(delta).not.toBeNull()
  expect(Number(delta![2]) * scale).toBeCloseTo(-90, 0)
  await act(async () => {
    document.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, clientX: 750, clientY: 390 }))
    host.querySelectorAll<HTMLElement>('[role="button"]')[2].click()
  })
  expect(onReorderColumn).toHaveBeenCalledWith('done', ['first', 'third', 'second'])
  expect(onOpenCard).not.toHaveBeenCalled()
})
