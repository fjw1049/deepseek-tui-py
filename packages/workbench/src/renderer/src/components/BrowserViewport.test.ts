// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { BrowserViewport } from './BrowserViewport'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const base = { image: 'data:image/jpeg;base64,AA==', width: 1200, height: 760, label: 'Page', resizeEnabled: false }

it('drops queued input after handoff and never cuts when clipboard writing fails', async () => {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  let resolve!: (value: { text?: string }) => void
  const send = vi.fn(() => new Promise<{ text?: string }>(done => { resolve = done }))
  const error = vi.fn()
  try {
    await act(async () => root.render(createElement(BrowserViewport, { ...base, enabled: true, generation: 1, send, onError: error })))
    const field = container.querySelector('textarea')!
    await act(async () => {
      field.value = 'first'; field.dispatchEvent(new InputEvent('input', { bubbles: true }))
      field.value = 'stale'; field.dispatchEvent(new InputEvent('input', { bubbles: true }))
    })
    expect(send).toHaveBeenCalledTimes(1)
    await act(async () => root.render(createElement(BrowserViewport, { ...base, enabled: false, generation: 2, send, onError: error })))
    await act(async () => resolve({}))
    expect(send).toHaveBeenCalledTimes(1)
    const clipboard = vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('Clipboard denied'))
    const copy = vi.fn(async () => ({ text: 'selected' }))
    await act(async () => root.render(createElement(BrowserViewport, { ...base, enabled: true, generation: 3, send: copy, onError: error })))
    await act(async () => field.dispatchEvent(new KeyboardEvent('keydown', { key: 'x', ctrlKey: true, bubbles: true })))
    expect(copy).toHaveBeenCalledExactlyOnceWith({ kind: 'copy', generation: 3 })
    expect(error).toHaveBeenCalledWith('Clipboard denied')
    clipboard.mockRestore()
  } finally { await act(async () => root.unmount()); container.remove() }
})

it('maps letterboxed coordinates and keeps wheel scrolling inside the webpage', async () => {
  const container = document.createElement('div'); const root = createRoot(container)
  const send = vi.fn(async () => ({}))
  try {
    await act(async () => root.render(createElement(BrowserViewport, { ...base, enabled: true, generation: 1, send, onError: vi.fn() })))
    const viewport = container.querySelector<HTMLDivElement>('.ds-browser-viewport')!
    vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue({ left: 10, top: 20, width: 600, height: 600 } as DOMRect)
    await act(async () => viewport.dispatchEvent(new PointerEvent('pointerdown', { clientX: 310, clientY: 320, button: 0, buttons: 1, bubbles: true })))
    expect(send).toHaveBeenCalledWith(expect.objectContaining({ x: 600, y: 380, event: 'mousePressed', generation: 1 }))
    const wheel = new WheelEvent('wheel', { clientX: 310, clientY: 320, deltaY: 30, bubbles: true, cancelable: true })
    Object.defineProperties(wheel, { clientX: { value: 310 }, clientY: { value: 320 } })
    await act(async () => viewport.dispatchEvent(wheel))
    expect(wheel.defaultPrevented).toBe(true)
    expect(send).toHaveBeenCalledWith(expect.objectContaining({ kind: 'wheel', delta_y: 30 }))
  } finally { await act(async () => root.unmount()) }
})

it('selects an element without activating it and cancels selection with Escape', async () => {
  const container = document.createElement('div'); const root = createRoot(container)
  const send = vi.fn(async () => ({})); const cancel = vi.fn()
  try {
    await act(async () => root.render(createElement(BrowserViewport, { ...base, enabled: true, inspect: true, onInspectCancel: cancel, generation: 1, send, onError: vi.fn() })))
    const viewport = container.querySelector<HTMLDivElement>('.ds-browser-viewport')!
    vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 1200, height: 760 } as DOMRect)
    await act(async () => {
      viewport.dispatchEvent(new PointerEvent('pointerdown', { clientX: 30, clientY: 40, button: 0, buttons: 1, bubbles: true }))
      viewport.dispatchEvent(new PointerEvent('pointerup', { clientX: 30, clientY: 40, button: 0, bubbles: true }))
    })
    expect(send).toHaveBeenCalledExactlyOnceWith({ kind: 'pick', x: 30, y: 40, generation: 1 })
    await act(async () => container.querySelector('textarea')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(cancel).toHaveBeenCalledOnce()
  } finally { await act(async () => root.unmount()) }
})
