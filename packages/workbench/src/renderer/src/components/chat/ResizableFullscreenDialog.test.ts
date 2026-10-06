// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { ResizableFullscreenDialog } from './ResizableFullscreenDialog'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

it('contains keyboard focus and returns it to the opener on close', async () => {
  const opener = document.createElement('button')
  const host = document.createElement('div')
  document.body.append(opener, host)
  opener.focus()
  const root = createRoot(host)
  const close = vi.fn()
  const key = async (value: string, shiftKey = false) => act(async () => {
    document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: value, shiftKey, bubbles: true, cancelable: true }))
  })
  try {
    await act(async () => root.render(createElement(ResizableFullscreenDialog, {
      open: true, onClose: close, ariaLabel: 'Preview', header: createElement('button', null, 'Close'),
      children: createElement('button', null, 'Copy'), overlayClassName: '', panelClassName: '', bodyClassName: ''
    })))
    const panel = document.querySelector<HTMLElement>('.ds-expand-panel')!
    const buttons = panel.querySelectorAll('button')
    expect(document.activeElement).toBe(panel)
    await key('Tab')
    expect(document.activeElement).toBe(buttons[0])
    await key('Tab', true)
    expect(document.activeElement).toBe(buttons[1])
    await key('Tab')
    expect(document.activeElement).toBe(buttons[0])
    await key('Escape')
    expect(close).toHaveBeenCalledOnce()
  } finally {
    await act(async () => root.unmount())
    expect(document.activeElement).toBe(opener)
    opener.remove()
    host.remove()
  }
})
