import { useLightDismiss } from '../hooks/use-light-dismiss'
// @vitest-environment happy-dom
import { act, createElement, useRef, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { GlobalErrorNotice, GlobalFeedbackViewport } from './GlobalFeedback'
import { reportActionError, useFeedbackStore } from '../store/feedback-store'
import { copyText } from '../lib/copy-text'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('i18next', () => ({ default: { t: (key: string) => key } }))
let host: HTMLDivElement
let root: Root
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  useFeedbackStore.setState({ failures: [] })
})
afterEach(() => { act(() => root.unmount()); host.remove(); vi.useRealTimers(); vi.restoreAllMocks() })

it('finds the shared viewport on the first mount, stacks errors and dismisses them independently', async () => {
  vi.useFakeTimers()
  const dismiss = vi.fn()
  await act(async () => root.render(createElement('div', null,
    createElement('div', { id: 'global-feedback-viewport' }),
    createElement('section', null,
      createElement(GlobalErrorNotice, { message: 'First failed', onDismiss: dismiss }),
      createElement(GlobalErrorNotice, { message: 'Second failed' })))))
  const viewport = host.querySelector('#global-feedback-viewport')!
  expect(viewport.querySelectorAll('[role="alert"]')).toHaveLength(2)
  expect(host.querySelector('section')?.textContent).toBe('')
  act(() => vi.advanceTimersByTime(60000))
  expect(viewport.querySelectorAll('[role="alert"]')).toHaveLength(2)
  act(() => viewport.querySelector<HTMLButtonElement>('button')!.click())
  expect(dismiss).toHaveBeenCalledOnce()
  expect(viewport.textContent).toBe('Second failed')
  await act(async () => root.render(null))
  expect(document.querySelector('[role="alert"]')).toBeNull()
})

it('retains imperative failures across view changes, deduplicates repeats and permits reporting after dismissal', () => {
  reportActionError(new Error('Clipboard failed'))
  reportActionError('Clipboard failed')
  reportActionError('Save failed')
  expect(useFeedbackStore.getState().failures.map(item => item.message)).toEqual(['Clipboard failed', 'Save failed'])
  useFeedbackStore.getState().dismiss(useFeedbackStore.getState().failures[0].id)
  reportActionError('Clipboard failed')
  expect(useFeedbackStore.getState().failures.map(item => item.message)).toEqual(['Save failed', 'Clipboard failed'])
})

it('reports a rejected clipboard write without claiming success or throwing an unhandled rejection', async () => {
  const writeText = vi.fn().mockRejectedValue(new Error('Denied'))
  vi.spyOn(navigator, 'clipboard', 'get').mockReturnValue({ writeText } as unknown as Clipboard)
  expect(await copyText('text')).toBe(false)
  expect(useFeedbackStore.getState().failures[0].message).toBe('common:copyFailed')
  writeText.mockResolvedValue(undefined)
  expect(await copyText('text')).toBe(true)
  expect(writeText).toHaveBeenCalledTimes(2)
})

it('reopens an identical failure from a new attempt without reopening on an unrelated render', async () => {
  const firstAttempt = {}
  const render = (occurrence: object) => root.render(createElement(GlobalErrorNotice, { message: 'Save failed', occurrence }))
  await act(async () => render(firstAttempt))
  act(() => host.querySelector<HTMLButtonElement>('button')!.click())
  expect(host.querySelector('[role="alert"]')).toBeNull()
  await act(async () => render(firstAttempt))
  expect(host.querySelector('[role="alert"]')).toBeNull()
  await act(async () => render({}))
  expect(host.querySelector('[role="alert"]')?.textContent).toBe('Save failed')
})

it('mounts the shared stack outside clipped panes and cleans up its portalled notices', async () => {
  await act(async () => root.render(createElement('section', { style: { overflow: 'hidden', transform: 'translateX(10px)' } },
    createElement(GlobalFeedbackViewport, null),
    createElement(GlobalErrorNotice, { message: 'Visible outside pane' }))))
  const viewport = document.getElementById('global-feedback-viewport')!
  expect(viewport.parentElement).toBe(document.body)
  expect(viewport.querySelector('[role="alert"]')?.textContent).toBe('Visible outside pane')
  expect(host.querySelector('[role="alert"]')).toBeNull()
  await act(async () => root.render(null))
  expect(document.getElementById('global-feedback-viewport')).toBeNull()
})

it('keeps a source popover open when dismissing its global error', async () => {
  vi.useFakeTimers()
  function Panel() {
    const [open, setOpen] = useState(true)
    const panelRef = useRef<HTMLDivElement>(null)
    useLightDismiss({ open, onDismiss: () => setOpen(false), refs: [panelRef] })
    return createElement('div', null, createElement(GlobalFeedbackViewport, null),
      open ? createElement('div', { ref: panelRef }, 'Source panel', createElement(GlobalErrorNotice, { message: 'Failed' })) : null)
  }
  await act(async () => root.render(createElement(Panel)))
  act(() => vi.runOnlyPendingTimers())
  const close = document.querySelector<HTMLButtonElement>('#global-feedback-viewport button')!
  act(() => close.dispatchEvent(new Event('pointerdown', { bubbles: true })))
  expect(host.textContent).toContain('Source panel')
  act(() => close.click())
  expect(document.querySelector('[role="alert"]')).toBeNull()
  expect(host.textContent).toContain('Source panel')
})
