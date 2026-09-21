// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { ChatSplitToolbar } from './ChatSplitToolbar'
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

it('exposes the selected arrangement, disables the fifth pane without a pane count or exit control', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const onArrange = vi.fn(), onAdd = vi.fn()
  await act(async () => root.render(createElement(ChatSplitToolbar, {
    layout: { panes: ['a', 'b', 'c', 'd'].map(id => ({ id, threadId: id })), focused: 'a', x: .5, y: .5, arrangement: 'grid' },
    onArrange, onAdd
  })))
  expect(host.querySelector('[aria-label="splitGrid"]')!.getAttribute('aria-pressed')).toBe('true')
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-label="splitVertical"]')!.click())
  expect(onArrange).toHaveBeenCalledWith('vertical')
  expect(host.querySelector<HTMLButtonElement>('[aria-label="splitAddPane"]')!.disabled).toBe(true)
  expect(host.querySelector('[aria-label="splitExit"]')).toBeNull()
  expect(host.querySelector('.ds-chat-split-toolbar-label')!.textContent).toBe('splitAdd')
  expect(onAdd).not.toHaveBeenCalled()
  await act(async () => root.unmount())
  host.remove()
})
