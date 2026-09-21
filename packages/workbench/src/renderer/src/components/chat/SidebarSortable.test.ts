// @vitest-environment happy-dom
import { act, createElement, type ComponentProps } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import type { DndContext } from '@dnd-kit/core'
import { SidebarSortableList } from './SidebarSortable'

const captured = vi.hoisted(() => ({ props: null as ComponentProps<typeof DndContext> | null }))
vi.mock('@dnd-kit/core', async importOriginal => ({
  ...await importOriginal<typeof import('@dnd-kit/core')>(),
  DndContext: (props: ComponentProps<typeof DndContext>) => { captured.props = props; return props.children }
}))
vi.mock('../../lib/chat-split-navigation', () => ({ CHAT_SPLIT_DRAG_EVENT: 'test-split-drag', finishChatSplitDrag: () => false }))

it('enables dragging a single sidebar item and ignores drops outside the list', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const onReorder = vi.fn()
  await act(async () => root.render(createElement(SidebarSortableList, { items: ['a'], onReorder, children: 'a' })))
  expect(captured.props?.onDragEnd).toBeTypeOf('function')
  await act(async () => root.render(createElement(SidebarSortableList, { items: ['a', 'b'], onReorder, children: 'a b' })))
  const active = { id: 'a', data: { current: undefined }, rect: { current: { initial: null, translated: null } } }
  const event = { active, activatorEvent: new PointerEvent('pointerdown', { clientX: 10, clientY: 10 }),
    delta: { x: 500, y: 20 }, collisions: [], over: { id: 'b', disabled: false, data: { current: undefined }, rect: { left: 0, right: 100, top: 20, bottom: 60, width: 100, height: 40 } } }
  captured.props!.onDragMove!(event)
  captured.props!.onDragEnd!(event)
  expect(onReorder).not.toHaveBeenCalled()
  captured.props!.onDragMove!({ ...event, delta: { x: 0, y: 20 } })
  captured.props!.onDragEnd!(event)
  expect(onReorder).toHaveBeenCalledWith(['b', 'a'])
  await act(async () => root.unmount())
  host.remove()
})
