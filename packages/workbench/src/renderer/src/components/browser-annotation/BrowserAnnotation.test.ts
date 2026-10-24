// @vitest-environment happy-dom
import { act, createElement, createRef } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { AnnotationMark } from '../../lib/browser-annotation'
import { BrowserAnnotation, type BrowserAnnotationHandle } from './BrowserAnnotation'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const composite = vi.hoisted(() => vi.fn(async (_url: string, _marks: readonly AnnotationMark[], _box: unknown) => new Blob(['png'], { type: 'image/png' })))
vi.mock('../../lib/browser-annotation', async (original) => ({ ...await original<object>(), compositeAnnotation: composite }))

const BACKDROP = 'data:image/png;base64,AAAA'
let root: Root
let container: HTMLDivElement

beforeEach(() => {
  composite.mockClear()
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ x: 0, y: 0, left: 0, top: 0, width: 800, height: 500, right: 800, bottom: 500, toJSON: () => ({}) })
  container = document.createElement('div'); document.body.append(container)
  root = createRoot(container)
})
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks() })

type Props = Parameters<typeof BrowserAnnotation>[0]
/** Mounts the bar with the pane's picking state held in the harness, like BrowserWorkspace does. */
function mount(overrides: Partial<Props> = {}) {
  const handle = createRef<BrowserAnnotationHandle>()
  const props = {
    disabled: false, pickEnabled: true, picking: false, capture: vi.fn(async () => BACKDROP), onAdd: vi.fn(async () => true),
    onHide: vi.fn(), onError: vi.fn(), ...overrides
  }
  const onPickingChange = vi.fn((next: boolean) => { props.picking = next; void render() })
  const render = () => act(async () => root.render(createElement(BrowserAnnotation, { ...props, onPickingChange, ref: handle })))
  return { props, handle, onPickingChange, render }
}
const everywhere = (): HTMLElement[] => [...document.body.querySelectorAll<HTMLElement>('button')]
const button = (label: string): HTMLButtonElement | undefined =>
  everywhere().find(b => b.getAttribute('aria-label') === label || b.textContent === label) as HTMLButtonElement | undefined
const click = (label: string) => act(async () => { const target = button(label); expect(target, label).toBeTruthy(); target!.click() })
const pressed = (): string[] => everywhere().filter(b => b.getAttribute('aria-pressed') === 'true').map(b => b.getAttribute('aria-label')!)
async function freeze(tool = 'annotationPen'): Promise<HTMLCanvasElement> {
  await click(tool)
  const image = container.querySelector('img')!
  Object.defineProperty(image, 'naturalWidth', { value: 1600 })
  Object.defineProperty(image, 'naturalHeight', { value: 1000 })
  await act(async () => { image.dispatchEvent(new Event('load')) })
  return container.querySelector('canvas')!
}
const pointer = (target: Element, type: string, x: number, y: number) => act(async () => {
  target.dispatchEvent(new PointerEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0, pointerId: 1 }))
})
async function stroke(canvas: Element, from: [number, number], to: [number, number]): Promise<void> {
  await pointer(canvas, 'pointerdown', ...from)
  await pointer(canvas, 'pointermove', ...to)
  await pointer(canvas, 'pointerup', ...to)
}

it('rests on the live page with only the tools and a hide button', async () => {
  const h = mount()
  await h.render()
  expect(pressed()).toEqual([])
  expect(button('annotationAdd')).toBeUndefined()
  expect(button('annotationColor')).toBeUndefined()
  expect(container.querySelector('.ds-annotation__stage')).toBeNull()
  await click('annotationHide')
  expect(h.props.onHide).toHaveBeenCalledOnce()
})

it('picks with the cursor: full bar, Add disabled with a reason, and the cursor toggles back to rest', async () => {
  const h = mount()
  await h.render()
  await click('annotationPick')
  expect(h.onPickingChange).toHaveBeenLastCalledWith(true)
  expect(pressed()).toEqual(['annotationPick'])
  expect(button('annotationColor')).toBeTruthy()
  expect(button('annotationAdd')?.disabled).toBe(true)
  expect(button('annotationAdd')?.parentElement?.getAttribute('title')).toBe('annotationAddPickHint')
  expect(h.props.capture).not.toHaveBeenCalled()
  await click('annotationClose')
  expect(h.onPickingChange).toHaveBeenLastCalledWith(false)
  expect(button('annotationHide')).toBeTruthy()
})

it('freezes the page when a drawing tool is chosen, leaving selection mode', async () => {
  const h = mount({ picking: true })
  await h.render()
  await freeze()
  expect(h.onPickingChange).toHaveBeenLastCalledWith(false)
  expect(h.props.capture).toHaveBeenCalledOnce()
  expect(pressed()).toEqual(['annotationPen'])
  expect(container.querySelector('img')?.getAttribute('src')).toBe(BACKDROP)
  expect(button('annotationAdd')?.disabled).toBe(false)
  expect(button('annotationUndo')).toBeUndefined()
  await click('annotationRect')
  expect(h.props.capture).toHaveBeenCalledOnce()
})

it('adds a drawn rectangle to the chat at the frozen frame size, then returns to rest', async () => {
  const h = mount()
  await h.render()
  await freeze('annotationRect')
  await stroke(container.querySelector('canvas')!, [10, 20], [110, 80])
  await click('annotationAdd')
  expect(composite).toHaveBeenCalledWith(BACKDROP, [{ kind: 'rect', x1: 10, y1: 20, x2: 110, y2: 80, color: '#E03131', width: 4 }], { width: 800, height: 500 })
  const [file, annotated] = vi.mocked(h.props.onAdd).mock.calls[0] as unknown as [File, boolean]
  expect([file.name, annotated]).toEqual(['browser-annotation.png', true])
  expect(container.querySelector('.ds-annotation__stage')).toBeNull()
  expect(button('annotationHide')).toBeTruthy()
})

it('keeps the marks when the chat does not take the image', async () => {
  const h = mount({ onAdd: vi.fn(async () => false) })
  await h.render()
  await stroke(await freeze('annotationRect'), [10, 20], [110, 80])
  await click('annotationAdd')
  expect(h.props.onAdd).toHaveBeenCalledOnce()
  expect(container.querySelector('.ds-annotation__stage')).toBeTruthy()
  expect(button('annotationUndo')?.disabled).toBe(false)
  expect(button('annotationAdd')?.disabled).toBe(false)
})

it('drops the hide button and its divider while the bar must stay up', async () => {
  const h = mount({ closable: false })
  await h.render()
  expect(button('annotationHide')).toBeUndefined()
  expect(container.querySelector('.ds-annotation-toolbar')!.lastElementChild?.className).not.toContain('divider')
})

it('sends a plain screenshot when nothing was drawn, and ignores stray clicks', async () => {
  const h = mount()
  await h.render()
  await freeze('annotationRect')
  await stroke(container.querySelector('canvas')!, [10, 10], [12, 12])
  await click('annotationAdd')
  expect(composite.mock.calls[0]![1]).toEqual([])
  expect((vi.mocked(h.props.onAdd).mock.calls[0] as unknown as [File, boolean])[0].name).toBe('browser-screenshot.png')
})

it('shows undo, redo and clear once there is history; clear is itself undoable', async () => {
  const h = mount()
  await h.render()
  const canvas = await freeze()
  await stroke(canvas, [5, 5], [40, 40])
  expect(button('annotationUndo')?.disabled).toBe(false)
  expect(button('annotationRedo')?.disabled).toBe(true)
  await click('annotationClear')
  expect(button('annotationClear')?.disabled).toBe(true)
  await click('annotationUndo')
  await click('annotationAdd')
  expect(composite.mock.calls[0]![1]).toHaveLength(1)
})

it('confirms in a dialog before discarding marks, from close and from the cursor', async () => {
  const h = mount()
  await h.render()
  await stroke(await freeze(), [5, 5], [5, 5])
  await click('annotationClose')
  expect(document.body.querySelector('[role="alertdialog"], [role="dialog"]')?.textContent).toContain('annotationDiscardTitle')
  await click('annotationKeepEditing')
  expect(button('annotationAdd')).toBeTruthy()
  await act(async () => h.handle.current!.togglePick())
  await click('annotationDiscard')
  expect(container.querySelector('.ds-annotation__stage')).toBeNull()
  expect(h.onPickingChange).toHaveBeenLastCalledWith(true)
  expect(h.props.onHide).not.toHaveBeenCalled()
})

it('closes an unmarked sketch and leaves selection with Escape, without asking', async () => {
  const h = mount({ picking: true })
  await h.render()
  const layer = container.querySelector('.ds-annotation')!
  await act(async () => { layer.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
  expect(h.onPickingChange).toHaveBeenLastCalledWith(false)
  await freeze()
  await act(async () => { layer.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
  expect(container.querySelector('.ds-annotation__stage')).toBeNull()
  expect(h.props.onHide).not.toHaveBeenCalled()
})

it('does not commit text while an IME is composing; Cmd+Enter commits and Escape discards', async () => {
  const h = mount()
  await h.render()
  const canvas = await freeze('annotationText')
  await pointer(canvas, 'pointerdown', 40, 50)
  let textarea = container.querySelector('textarea')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(textarea, '这里')
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await act(async () => { textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, keyCode: 229, bubbles: true })) })
  expect(container.querySelector('textarea')).toBeTruthy()
  await act(async () => { textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', metaKey: true, bubbles: true })) })
  expect(container.querySelector('textarea')).toBeNull()
  await pointer(canvas, 'pointerdown', 200, 200)
  textarea = container.querySelector('textarea')!
  await act(async () => { textarea.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })) })
  expect(container.querySelector('textarea')).toBeNull()
  expect(container.querySelector('.ds-annotation__stage')).toBeTruthy()
  await click('annotationAdd')
  expect(composite.mock.calls[0]![1]).toEqual([{ kind: 'text', x: 40, y: 50, text: '这里', size: 18, color: '#E03131' }])
})

it('undoes and redoes with the keyboard', async () => {
  const h = mount()
  await h.render()
  await stroke(await freeze(), [5, 5], [30, 30])
  const layer = container.querySelector('.ds-annotation')!
  await act(async () => { layer.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', metaKey: true, bubbles: true })) })
  await act(async () => { layer.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', metaKey: true, shiftKey: true, bubbles: true })) })
  await act(async () => { layer.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', metaKey: true, bubbles: true })) })
  await click('annotationAdd')
  expect(composite.mock.calls[0]![1]).toEqual([])
})

it('maps pointer positions through the UI zoom into layout pixels', async () => {
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(640)
  const h = mount()
  await h.render()
  await freeze('annotationRect')
  await stroke(container.querySelector('canvas')!, [100, 50], [300, 250])
  await click('annotationAdd')
  // 800 client px over 640 layout px is a 1.25 zoom.
  expect(composite.mock.calls[0]![1]).toEqual([{ kind: 'rect', x1: 80, y1: 40, x2: 240, y2: 200, color: '#E03131', width: 4 }])
  expect(composite.mock.calls[0]![2]).toEqual({ width: 640, height: 400 })
})

it('returns to rest when the screenshot fails', async () => {
  const h = mount({ capture: vi.fn(async () => { throw new Error('Screenshot timed out.') }) })
  await h.render()
  await click('annotationPen')
  expect(h.props.onError).toHaveBeenCalledWith('Screenshot timed out.')
  expect(pressed()).toEqual([])
  expect(container.querySelector('.ds-annotation__stage')).toBeNull()
})

it('disables every tool while the page cannot be annotated', async () => {
  const h = mount({ disabled: true })
  await h.render()
  for (const label of ['annotationPick', 'annotationPen', 'annotationRect', 'annotationText']) expect(button(label)?.disabled, label).toBe(true)
  expect(button('annotationHide')?.disabled).toBe(false)
})
