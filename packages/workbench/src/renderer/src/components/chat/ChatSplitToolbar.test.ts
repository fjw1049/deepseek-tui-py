// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { ChatSplitToolbar } from './ChatSplitToolbar'
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

it('exposes the selected arrangement, disables the seventh pane without a pane count or exit control', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const onArrange = vi.fn(), onAdd = vi.fn()
  await act(async () => root.render(createElement(ChatSplitToolbar, {
    layout: { panes: ['a', 'b', 'c', 'd', 'e', 'f'].map(id => ({ id, threadId: id })), focused: 'a', x: .5, y: .5, arrangement: 'grid' },
    onArrange, onAdd
  })))
  const trigger = host.querySelector<HTMLButtonElement>('[aria-haspopup="dialog"]')!
  expect(trigger.textContent).toBe('splitArrangement')
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  await act(async () => trigger.click())
  const panel = document.querySelector('[role="dialog"]')!
  const options = [...panel.querySelectorAll<HTMLButtonElement>('button')]
  expect(options.map(button => button.textContent)).toEqual(['splitGrid', 'splitHorizontal', 'splitVertical'])
  expect(options[0].getAttribute('aria-pressed')).toBe('true')
  await act(async () => options[2].click())
  expect(onArrange).toHaveBeenCalledWith('vertical')
  expect(host.querySelector<HTMLButtonElement>('[aria-label="splitAddPane"]')!.disabled).toBe(true)
  expect(host.querySelector('[aria-label="splitExit"]')).toBeNull()
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  expect(document.activeElement).toBe(trigger)
  await act(async () => trigger.click())
  await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  expect(document.activeElement).toBe(trigger)
  expect(onAdd).not.toHaveBeenCalled()
  await act(async () => root.unmount())
  host.remove()
})
