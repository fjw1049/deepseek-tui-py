// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { SessionQueries } from './SessionQueries'

let state = { activeThreadId: 'one', blocks: Array.from({ length: 12 }, (_, i) => ({
  kind: 'user', id: String(i), text: `Query ${i}\n${'完整文本 '.repeat(100)}`
})) }
vi.mock('../store/chat-store', () => ({ useChatStore: (select: (s: typeof state) => unknown) => select(state) }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true

afterEach(() => { vi.useRealTimers(); document.body.innerHTML = '' })

it('lists all queries newest first, bridges hover between title and list, copies full text, and resets on session switch', async () => {
  vi.useFakeTimers()
  const writeText = vi.fn().mockResolvedValue(undefined)
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  await act(async () => root.render(createElement(SessionQueries, null, 'Session')))
  const trigger = container.querySelector('button')!
  const click = (detail: number) => trigger.dispatchEvent(new MouseEvent('click', { bubbles: true, detail }))
  await act(async () => trigger.dispatchEvent(new PointerEvent('pointerover', { bubbles: true, pointerType: 'mouse' })))
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  await act(async () => { click(1); click(2); trigger.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })) })
  await act(async () => vi.advanceTimersByTime(350))
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  expect(writeText).toHaveBeenLastCalledWith(state.blocks[11]!.text)
  await act(async () => click(1))
  await act(async () => vi.advanceTimersByTime(350))
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  const rows = document.body.querySelectorAll('button[title="sessionQueryCopyHint"]')
  expect(rows).toHaveLength(12)
  expect(rows[0]!.textContent).toMatch(/^Query 11 /)
  expect(rows[11]!.textContent).toMatch(/^Query 0 /)
  expect(rows[0]!.textContent!.length).toBeLessThan(state.blocks[11]!.text.length)
  expect((rows[0]!.parentElement as HTMLElement).style.maxHeight).toBe('360px')
  await act(async () => rows[5]!.dispatchEvent(new MouseEvent('dblclick', { bubbles: true })))
  expect(writeText).toHaveBeenLastCalledWith(state.blocks[6]!.text)
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  const panel = rows[0]!.parentElement!.parentElement!
  await act(async () => {
    trigger.dispatchEvent(new PointerEvent('pointerout', { bubbles: true, pointerType: 'mouse', relatedTarget: document.body }))
    vi.advanceTimersByTime(100)
    panel.dispatchEvent(new PointerEvent('pointerover', { bubbles: true, pointerType: 'mouse', relatedTarget: document.body }))
    vi.advanceTimersByTime(200)
  })
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  await act(async () => {
    panel.dispatchEvent(new PointerEvent('pointerout', { bubbles: true, pointerType: 'mouse', relatedTarget: document.body }))
    vi.advanceTimersByTime(200)
  })
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  await act(async () => trigger.click())
  await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  await act(async () => trigger.click())
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  state = { activeThreadId: 'two', blocks: [] }
  await act(async () => root.render(createElement(SessionQueries, null, 'Other')))
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  expect(trigger.disabled).toBe(true)
  await act(async () => root.unmount())
})
