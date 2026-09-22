// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { InlineTodoBlock } from './InlineTodoBlock'
import type { TodoTurnSession } from '../../lib/extract-todos-from-blocks'
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, options?: { done: number; total: number }) => key === 'todoInlineProgress' ? `${options?.done}/${options?.total} done` : key }) }))

it('folds complete and incomplete summaries by default and allows reopening', () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  const root = createRoot(host)
  const session: TodoTurnSession = { anchorBlockId: 'one', todoBlockIds: ['one'], items: [{ id: 'a', content: 'Review files', status: 'in_progress' }], completionPct: 0, inProgressId: 'a', isComplete: false }
  const render = (value: TodoTurnSession) => act(() => root.render(createElement(InlineTodoBlock, { session: value })))
  try {
    render(session)
    expect(host.querySelector('button')?.getAttribute('aria-expanded')).toBe('false')
    const done: TodoTurnSession = { ...session, isComplete: true, inProgressId: null, completionPct: 100, items: [{ ...session.items[0], status: 'completed' }] }
    render(done)
    expect(host.querySelector('ul')).toBeNull()
    act(() => host.querySelector('button')!.click())
    expect(host.querySelector('li')?.textContent).toContain('Review files')
    render({ ...done })
    expect(host.querySelector('ul')).not.toBeNull()
    render({ ...session, anchorBlockId: 'two' })
    expect(host.querySelector('button')?.getAttribute('aria-expanded')).toBe('false')
  } finally { act(() => root.unmount()) }
})

it('preserves row identity and order when content and status change, and only spins during active work', () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  const root = createRoot(host)
  const session: TodoTurnSession = {
    anchorBlockId: 'stable', todoBlockIds: ['stable'], completionPct: 0, inProgressId: 'a', isComplete: false,
    items: [{ id: 'a', content: '检查中文长任务描述和文件路径', status: 'in_progress' }, { id: 'b', content: 'Run checks', status: 'pending' }]
  }
  try {
    act(() => root.render(createElement(InlineTodoBlock, { session, active: true })))
    act(() => host.querySelector('button')!.click())
    const firstRow = host.querySelector('li')
    expect(host.querySelectorAll('.ds-inline-todo__spinner')).toHaveLength(1)
    const updated: TodoTurnSession = { ...session, inProgressId: 'b', items: [{ ...session.items[0], content: 'Reviewed files', status: 'completed' }, { ...session.items[1], status: 'in_progress' }] }
    act(() => root.render(createElement(InlineTodoBlock, { session: updated, active: false })))
    expect(host.querySelector('li')).toBe(firstRow)
    expect(Array.from(host.querySelectorAll('li')).map((row) => row.dataset.status)).toEqual(['completed', 'in_progress'])
    expect(host.querySelectorAll('button')).toHaveLength(1)
    expect(host.querySelector('.ds-inline-todo__spinner')).toBeNull()
    act(() => host.querySelector('button')!.click())
    expect(host.querySelector('[role="region"]')?.hasAttribute('hidden')).toBe(true)
    expect(host.querySelector('[title="Run checks"]')).toBeNull()
    expect(host.querySelector('button')?.getAttribute('aria-controls')).toBe(host.querySelector('[role="region"]')?.id)
  } finally { act(() => root.unmount()) }
})

it('reports cancelled items separately and never presents a partially cancelled plan as full success', () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  const root = createRoot(host)
  const session: TodoTurnSession = {
    anchorBlockId: 'cancelled', todoBlockIds: ['cancelled'], completionPct: 50, inProgressId: null, isComplete: true,
    items: [{ id: 'a', content: 'Finished', status: 'completed' }, { id: 'b', content: 'Skipped', status: 'cancelled' }]
  }
  try {
    act(() => root.render(createElement(InlineTodoBlock, { session })))
    expect(host.querySelector('button')?.getAttribute('aria-expanded')).toBe('false')
    expect(host.querySelector('button')?.textContent).toContain('1/2')
    expect(host.querySelector('[role="status"]')?.textContent).toContain('todoInlineCancelled')
    expect(host.querySelector('.bg-emerald-500')).toBeNull()
    act(() => host.querySelector('button')!.click())
    expect(host.querySelectorAll('li')).toHaveLength(2)
    expect(host.querySelector('[data-status="cancelled"]')?.textContent).toContain('todoInlineStatus_cancelled')
  } finally { act(() => root.unmount()) }
})
