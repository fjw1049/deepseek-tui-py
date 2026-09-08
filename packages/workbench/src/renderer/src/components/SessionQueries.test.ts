// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { SessionQueries } from './SessionQueries'

const scrollToBlock = vi.fn()
let state = { scrollToBlock, activeThreadId: 'one', blocks: Array.from({ length: 12 }, (_, i) => ({
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
  expect((rows[0]!.parentElement!.parentElement as HTMLElement).style.maxHeight).toBe('360px')
  await act(async () => {
    rows[5]!.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 }))
    vi.advanceTimersByTime(100)
    rows[5]!.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 2 }))
    rows[5]!.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))
    vi.advanceTimersByTime(450)
  })
  expect(scrollToBlock).not.toHaveBeenCalled()
  expect(writeText).toHaveBeenLastCalledWith(state.blocks[6]!.text)
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  const copyButton = rows[4]!.parentElement!.querySelector('button[title="copyMessage"]')!
  await act(async () => {
    rows[4]!.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 }))
    copyButton.querySelector('svg')!.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 }))
  })
  await act(async () => vi.advanceTimersByTime(450))
  expect(writeText).toHaveBeenLastCalledWith(state.blocks[7]!.text)
  expect(copyButton.getAttribute('title')).toBe('copySuccess')
  expect(copyButton.querySelector('.lucide-check')).not.toBeNull()
  expect(scrollToBlock).not.toHaveBeenCalled()
  expect(trigger.getAttribute('aria-expanded')).toBe('true')
  expect(document.querySelector('button button')).toBeNull()
  const panel = rows[0]!.parentElement!.parentElement!.parentElement!
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
  const target = document.body.querySelectorAll('button[title="sessionQueryCopyHint"]')[3]!
  await act(async () => target.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })))
  expect(scrollToBlock).not.toHaveBeenCalled()
  await act(async () => vi.advanceTimersByTime(400))
  expect(scrollToBlock).toHaveBeenCalledExactlyOnceWith('8')
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  await act(async () => trigger.click())
  await act(async () => document.body.querySelector('button[title="sessionQueryCopyHint"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })))
  state = { scrollToBlock, activeThreadId: 'two', blocks: [] }
  await act(async () => root.render(createElement(SessionQueries, null, 'Other')))
  expect(trigger.getAttribute('aria-expanded')).toBe('false')
  expect(trigger.disabled).toBe(true)
  await act(async () => vi.advanceTimersByTime(450))
  expect(scrollToBlock).toHaveBeenCalledTimes(1)
  await act(async () => root.unmount())
})

it.each([false, true])('preserves the IDE typography scope across the portal (IDE=%s)', async (ide) => {
  state = { ...state, blocks: [{ kind: 'user', id: 'query', text: '测试 query' }] }
  const container = document.createElement('div')
  if (ide) container.className = 'ds-ide-chat-rail'
  document.body.append(container)
  const root = createRoot(container)
  await act(async () => root.render(createElement(SessionQueries, null, 'Session')))
  await act(async () => container.querySelector('button')!.click())
  const panel = document.querySelector('.ds-session-queries')!
  expect(panel.parentElement).toBe(document.body)
  expect(panel.classList.contains('ds-session-queries--ide')).toBe(ide)
  expect(panel.querySelector('.ds-session-query-row')).not.toBeNull()
  await act(async () => root.unmount())
})
