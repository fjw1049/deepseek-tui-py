// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { SessionHeader } from './SessionHeader'

const state = {
  activeThreadId: 'one',
  threads: [{ id: 'one', title: 'Question', mode: 'agent', updatedAt: new Date().toISOString() }],
  blocks: [{ kind: 'user', id: 'query', text: 'Full question' }],
  workspaceRoot: '', workspaceLabel: '', busy: false
}
vi.mock('../store/chat-store', () => ({ useChatStore: (select: (s: typeof state) => unknown) => select(state) }))
vi.mock('react-i18next', async (importOriginal) => ({
  ...await importOriginal<typeof import('react-i18next')>(),
  useTranslation: () => ({ t: (key: string) => key })
}))
globalThis.IS_REACT_ACT_ENVIRONMENT = true

it('keeps mode/time visible outside the query trigger', async () => {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  await act(async () => root.render(createElement(SessionHeader, { compact: true })))
  const button = container.querySelector('button')!
  const meta = container.querySelector('.ds-session-header-meta')!
  expect(meta.textContent).toContain('agent')
  expect(meta.querySelector('.tabular-nums')?.textContent).toBeTruthy()
  expect(button.contains(meta)).toBe(false)
  expect(button.textContent).toBe('Question')
  await act(async () => {
    meta.dispatchEvent(new PointerEvent('pointerover', { bubbles: true, pointerType: 'mouse' }))
    meta.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
  expect(button.getAttribute('aria-expanded')).toBe('false')
  await act(async () => button.click())
  expect(button.getAttribute('aria-expanded')).toBe('true')
  await act(async () => root.unmount())
  container.remove()
})
