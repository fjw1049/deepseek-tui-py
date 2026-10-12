// @vitest-environment happy-dom
import { act, createElement, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { ActivitySwipeRow } from './ActivitySwipeRow'
import { loadDismissedActivity, persistDismissedActivity } from '../../lib/sidebar-activity'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers() })

it('persists dismissed reminders across remounts and tolerates corrupt storage', () => {
  persistDismissedActivity({ thread: 'turn-1:failed' })
  expect(loadDismissedActivity()).toEqual({ thread: 'turn-1:failed' })
  localStorage.setItem('deepseekgui.sidebar.dismissedActivity', 'invalid')
  expect(loadDismissedActivity()).toEqual({})
  localStorage.clear()
})

it('drags left to reveal, right to close, ignores vertical scrolling, and never opens a conversation after dragging', async () => {
  vi.spyOn(window, 'getComputedStyle').mockReturnValue({ transform: 'none' } as CSSStyleDeclaration)
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList)
  const select = vi.fn(), dismiss = vi.fn()
  function Harness() {
    const [open, setOpen] = useState(false)
    return createElement(ActivitySwipeRow, { title: 'Conversation', selected: false, open,
      onOpenChange: setOpen, onSelect: select, onDismiss: dismiss, children: 'Conversation' })
  }
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  try {
    await act(async () => root.render(createElement(Harness)))
    const row = container.querySelector<HTMLButtonElement>('.ds-activity-row')!
    row.setPointerCapture = vi.fn()
    row.releasePointerCapture = vi.fn()
    const pointer = (type: string, x: number, y = 0) => row.dispatchEvent(new PointerEvent(type, {
      bubbles: true, pointerId: 1, isPrimary: true, button: 0, clientX: x, clientY: y
    }))
    await act(async () => row.click())
    expect(select).toHaveBeenCalledTimes(1)
    await act(async () => { pointer('pointerdown', 100); pointer('pointermove', 40); pointer('pointerup', 40) })
    expect(row.style.transform).toBe('translateX(-76px)')
    await act(async () => row.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })))
    expect(select).toHaveBeenCalledTimes(1)
    expect(row.style.transform).toBe('translateX(-76px)')
    await act(async () => { pointer('pointerdown', 40); pointer('pointermove', 100); pointer('pointerup', 100) })
    expect(row.style.transform).toBe('translateX(0px)')
    await act(async () => { pointer('pointerdown', 100); pointer('pointermove', 90, 50); pointer('pointerup', 90, 50) })
    expect(row.style.transform).toBe('translateX(0px)')
    await act(async () => row.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'ArrowLeft' })))
    expect(row.style.transform).toBe('translateX(-76px)')
    await act(async () => container.querySelector<HTMLButtonElement>('.ds-activity-dismiss')!.click())
    expect(dismiss).toHaveBeenCalledTimes(1)
    expect(select).toHaveBeenCalledTimes(1)
  } finally { await act(async () => root.unmount()); container.remove() }
})

it('accepts trackpad horizontal swipes without intercepting vertical wheel events', async () => {
  vi.useFakeTimers()
  vi.spyOn(window, 'getComputedStyle').mockReturnValue({ transform: 'none' } as CSSStyleDeclaration)
  const change = vi.fn()
  const container = document.createElement('div')
  const root = createRoot(container)
  try {
    await act(async () => root.render(createElement(ActivitySwipeRow, {
      title: 'Conversation', selected: false, open: false, onOpenChange: change,
      onSelect: vi.fn(), onDismiss: vi.fn(), children: 'Conversation'
    })))
    const shell = container.querySelector('.ds-activity-swipe')!
    const vertical = new WheelEvent('wheel', { deltaY: 80, cancelable: true })
    await act(async () => shell.dispatchEvent(vertical))
    expect(vertical.defaultPrevented).toBe(false)
    const horizontal = new WheelEvent('wheel', { deltaX: 60, cancelable: true })
    await act(async () => shell.dispatchEvent(horizontal))
    expect(horizontal.defaultPrevented).toBe(true)
    await act(async () => vi.advanceTimersByTime(100))
    expect(change).toHaveBeenCalledWith(true)
  } finally { await act(async () => root.unmount()); container.remove() }
})

it('finishes the collapse before dismissing and prevents repeated clicks', async () => {
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: false } as MediaQueryList)
  let finish!: () => void
  const finished = new Promise<void>((resolve) => { finish = resolve })
  const dismiss = vi.fn()
  const container = document.createElement('div')
  const root = createRoot(container)
  try {
    await act(async () => root.render(createElement(ActivitySwipeRow, {
      title: 'Conversation', selected: false, open: true, onOpenChange: vi.fn(),
      onSelect: vi.fn(), onDismiss: dismiss, children: 'Conversation'
    })))
    const shell = container.querySelector<HTMLElement>('.ds-activity-swipe')!
    shell.animate = vi.fn().mockReturnValue({ finished, cancel: vi.fn() })
    const button = container.querySelector<HTMLButtonElement>('.ds-activity-dismiss')!
    await act(async () => button.click())
    expect(dismiss).not.toHaveBeenCalled()
    expect(button.disabled).toBe(true)
    await act(async () => button.click())
    expect(shell.animate).toHaveBeenCalledTimes(1)
    await act(async () => finish())
    expect(dismiss).toHaveBeenCalledTimes(1)
  } finally { await act(async () => root.unmount()); container.remove() }
})
