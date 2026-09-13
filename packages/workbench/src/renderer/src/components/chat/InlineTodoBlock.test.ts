// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { InlineTodoBlock } from './InlineTodoBlock'
import type { TodoTurnSession } from '../../lib/extract-todos-from-blocks'
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

it('folds completed work, allows reopening, and expands a new running session', () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  const root = createRoot(host)
  const session: TodoTurnSession = { anchorBlockId: 'one', todoBlockIds: ['one'], items: [{ id: 'a', content: 'Review files', status: 'in_progress' }], completionPct: 0, inProgressId: 'a', isComplete: false }
  const render = (value: TodoTurnSession) => act(() => root.render(createElement(InlineTodoBlock, { session: value })))
  try {
    render(session)
    expect(host.querySelector('button')?.getAttribute('aria-expanded')).toBe('true')
    const done: TodoTurnSession = { ...session, isComplete: true, inProgressId: null, completionPct: 100, items: [{ ...session.items[0], status: 'completed' }] }
    render(done)
    expect(host.querySelector('ul')).toBeNull()
    act(() => host.querySelector('button')!.click())
    expect(host.querySelector('li')?.textContent).toContain('Review files')
    render({ ...done })
    expect(host.querySelector('ul')).not.toBeNull()
    render({ ...session, anchorBlockId: 'two' })
    expect(host.querySelector('button')?.getAttribute('aria-expanded')).toBe('true')
  } finally { act(() => root.unmount()) }
})
