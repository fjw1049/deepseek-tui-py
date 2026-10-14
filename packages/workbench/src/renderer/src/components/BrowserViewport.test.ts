// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { BrowserViewport } from './BrowserViewport'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const base = { image: 'data:image/jpeg;base64,AA==', width: 1200, height: 760, label: 'Page', resizeEnabled: false }

it('discards queued text after same-generation disable and scene replacement', async () => {
  const container = document.createElement('div'); const root = createRoot(container)
  let finish!: (value: {}) => void
  const send = vi.fn(() => new Promise<{}>(resolve => { finish = resolve }))
  try {
    await act(async () => root.render(createElement(BrowserViewport, { ...base, enabled: true, generation: 2, sceneId: 'old', send, onError: vi.fn() })))
    const field = container.querySelector('textarea')!
    await act(async () => {
      field.value = 'first'; field.dispatchEvent(new InputEvent('input', { bubbles: true }))
      field.value = 'old queued text'; field.dispatchEvent(new InputEvent('input', { bubbles: true }))
    })
    await act(async () => root.render(createElement(BrowserViewport, { ...base, enabled: false, generation: 2, sceneId: 'old', send, onError: vi.fn() })))
    await act(async () => root.render(createElement(BrowserViewport, { ...base, enabled: true, generation: 2, sceneId: 'new', send, onError: vi.fn() })))
    await act(async () => finish({}))
    expect(send).toHaveBeenCalledExactlyOnceWith({ kind: 'text', text: 'first', generation: 2, scene_id: 'old' })
  } finally { await act(async () => root.unmount()) }
})

it('keeps queued typing across a scene change but drops queued pointer input', async () => {
  const container = document.createElement('div'); const root = createRoot(container)
  let finish!: (value: {}) => void
  const send = vi.fn((input: Record<string, unknown>) => input.text === 'a'
    ? new Promise<{}>(resolve => { finish = resolve }) : Promise.resolve({}))
  try {
    await act(async () => root.render(createElement(BrowserViewport, { ...base, enabled: true, generation: 2, sceneId: 'old', send, onError: vi.fn() })))
    const field = container.querySelector('textarea')!
    const viewport = container.querySelector<HTMLDivElement>('.ds-browser-viewport')!
    vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 1200, height: 760 } as DOMRect)
    await act(async () => {
      field.value = 'a'; field.dispatchEvent(new InputEvent('input', { bubbles: true }))
      field.value = 'b'; field.dispatchEvent(new InputEvent('input', { bubbles: true }))
      viewport.dispatchEvent(new PointerEvent('pointerdown', { clientX: 30, clientY: 40, button: 0, buttons: 1, bubbles: true }))
    })
    // A live-search field rewrote the URL, so the runtime reported a new scene.
    await act(async () => root.render(createElement(BrowserViewport, { ...base, enabled: true, generation: 2, sceneId: 'new', send, onError: vi.fn() })))
    await act(async () => finish({}))
    expect(send.mock.calls.map(([input]) => input.kind)).toEqual(['text', 'text'])
    expect(send).toHaveBeenLastCalledWith({ kind: 'text', text: 'b', generation: 2, scene_id: 'old' })
  } finally { await act(async () => root.unmount()) }
})

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

it('coalesces queued motion without moving it across a click or losing scroll distance', async () => {
  const container = document.createElement('div'); const root = createRoot(container)
  let finish!: (value: {}) => void
  const send = vi.fn((input: Record<string, unknown>) => input.kind === 'text'
    ? new Promise<{}>(resolve => { finish = resolve }) : Promise.resolve({}))
  let now = 1000
  const clock = vi.spyOn(Date, 'now').mockImplementation(() => now += 50)
  try {
    await act(async () => root.render(createElement(BrowserViewport, { ...base, enabled: true, generation: 2, sceneId: 'same', send, onError: vi.fn() })))
    const field = container.querySelector('textarea')!
    const viewport = container.querySelector<HTMLDivElement>('.ds-browser-viewport')!
    vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 1200, height: 760 } as DOMRect)
    await act(async () => { field.value = 'hold'; field.dispatchEvent(new InputEvent('input', { bubbles: true })) })
    await act(async () => {
      for (let x = 10; x <= 100; x += 10) viewport.dispatchEvent(new PointerEvent('pointermove', { clientX: x, clientY: 40, bubbles: true }))
      viewport.dispatchEvent(new PointerEvent('pointerdown', { clientX: 100, clientY: 40, button: 0, buttons: 1, bubbles: true }))
      viewport.dispatchEvent(new PointerEvent('pointerup', { clientX: 100, clientY: 40, button: 0, bubbles: true }))
      for (let i = 0; i < 20; i++) {
        const wheel = new WheelEvent('wheel', { deltaY: 30, bubbles: true })
        Object.defineProperties(wheel, { clientX: { value: 100 }, clientY: { value: 40 } })
        viewport.dispatchEvent(wheel)
      }
    })
    expect(send).toHaveBeenCalledTimes(1)
    await act(async () => finish({}))
    expect(send.mock.calls.map(([input]) => input.event ?? input.kind)).toEqual(['text', 'mouseMoved', 'mousePressed', 'mouseReleased', 'wheel'])
    expect(send.mock.calls[1][0].x).toBe(100)
    expect(send.mock.calls[4][0].delta_y).toBe(600)
  } finally { clock.mockRestore(); await act(async () => root.unmount()) }
})
