// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { SessionHeader } from './SessionHeader'

const state = {
  activeThreadId: 'one', pinnedThreadIds: [],
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

it('keeps session information and query navigation as separate triggers', async () => {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  try {
    await act(async () => root.render(createElement(SessionHeader, { compact: true })))
    const info = container.querySelector<HTMLButtonElement>('button[aria-label="sessionInfoHint"]')!
    const query = [...container.querySelectorAll('button')].find(button => button.textContent === 'Question')!
    expect(info).not.toBe(query)
    await act(async () => info.click())
    expect(info.getAttribute('aria-expanded')).toBe('true')
    expect(query.getAttribute('aria-expanded')).toBe('false')
    await act(async () => info.click())
    await act(async () => query.click())
    expect(query.getAttribute('aria-expanded')).toBe('true')
    expect(info.getAttribute('aria-expanded')).toBe('false')
  } finally {
    await act(async () => root.unmount())
    container.remove()
  }
})
