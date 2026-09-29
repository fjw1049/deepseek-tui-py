// @vitest-environment happy-dom
import { act, createElement, useRef } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { useStartupWindowDrag } from './use-startup-window-drag'

it('arms after 0.5s, tolerates jitter, locks the gesture, and cleans up on exit', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  const drag = vi.fn()
  vi.stubGlobal('dsGui', { startupWindowDrag: drag })
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  function Board({ enabled = true }): React.ReactElement {
    const ref = useRef<HTMLDivElement>(null)
    useStartupWindowDrag(ref, enabled)
    return createElement('div', { ref })
  }
  try {
    await act(async () => root.render(createElement(Board)))
    const board = container.firstElementChild as HTMLDivElement
    board.getBoundingClientRect = () => ({ left: 0, top: 0, width: 800, height: 600 }) as DOMRect
    let captured = false
    board.setPointerCapture = () => { captured = true }
    board.hasPointerCapture = () => captured
    board.releasePointerCapture = () => { captured = false }
    const send = (type: string, x = 300, y = 250, buttons = 0, button = 0): void => {
      board.dispatchEvent(new PointerEvent(type, { pointerId: 1, pointerType: 'mouse', clientX: x, clientY: y, buttons, button }))
    }
    const ready = (): void => {
      send('pointermove')
      vi.advanceTimersByTime(500)
      expect(board.dataset.windowDrag).toBe('ready')
    }
    send('pointermove')
    vi.advanceTimersByTime(499)
    expect(board.dataset.windowDrag).toBeUndefined()
    send('pointermove', 303, 252)
    vi.advanceTimersByTime(1)
    expect(board.dataset.windowDrag).toBe('ready')
    send('pointermove', 320)
    expect(board.dataset.windowDrag).toBeUndefined()
    ready()
    send('pointerdown', 300, 250, 1)
    expect(drag).toHaveBeenLastCalledWith('start')
    expect(captured).toBe(true)
    send('pointerleave')
    send('pointermove', 900, 650, 1)
    expect(drag).toHaveBeenLastCalledWith('move')
    expect(board.dataset.windowDrag).toBe('dragging')
    send('pointerup', 900, 650)
    expect(drag).toHaveBeenLastCalledWith('end')
    expect(captured).toBe(false)
    expect(board.dataset.windowDrag).toBeUndefined()
    // Holding a button before the dwell completes must never turn into a drag.
    send('pointermove')
    send('pointerdown', 300, 250, 1)
    vi.advanceTimersByTime(1500)
    expect(board.dataset.windowDrag).toBeUndefined()
    send('pointermove', 300, 250, 1)
    vi.advanceTimersByTime(1500)
    expect(board.dataset.windowDrag).toBeUndefined()
    // Native resize edges and traffic lights are excluded.
    send('pointermove', 4)
    vi.advanceTimersByTime(500)
    expect(board.dataset.windowDrag).toBeUndefined()
    send('pointermove', 60, 25)
    vi.advanceTimersByTime(500)
    expect(board.dataset.windowDrag).toBeUndefined()
    ready()
    send('pointerdown', 300, 250, 2, 2)
    expect(board.dataset.windowDrag).toBeUndefined()
    ready()
    send('pointerdown', 300, 250, 1)
    window.dispatchEvent(new Event('blur'))
    expect(drag).toHaveBeenLastCalledWith('end')
    expect(board.dataset.windowDrag).toBeUndefined()
    send('pointermove')
    send('pointerleave')
    vi.advanceTimersByTime(500)
    expect(board.dataset.windowDrag).toBeUndefined()
    ready()
    send('pointerdown', 300, 250, 1)
    await act(async () => root.render(createElement(Board, { enabled: false })))
    expect(drag).toHaveBeenLastCalledWith('end')
    send('pointermove')
    vi.advanceTimersByTime(500)
    expect(board.dataset.windowDrag).toBeUndefined()
  } finally {
    await act(async () => root.unmount())
    container.remove()
    vi.unstubAllGlobals()
    vi.useRealTimers()
  }
})
