// @vitest-environment happy-dom
import { act, createElement, useRef } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { useModalFocus } from './use-modal-focus'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
function Form({ close }: { close: () => void }) {
  const panel = useRef<HTMLDivElement>(null)
  useModalFocus(true, panel, close)
  return createElement('div', { ref: panel, tabIndex: -1 },
    createElement('input', { 'aria-label': 'Name' }), createElement('button', { disabled: true }, 'Pending'),
    createElement('button', null, 'Cancel'))
}
it('contains focus, ignores Escape during composition and returns focus on close', async () => {
  const opener = document.createElement('button'), host = document.createElement('div')
  document.body.append(opener, host); opener.focus()
  const root = createRoot(host), close = vi.fn()
  const key = (key: string, shiftKey = false, isComposing = false) => act(async () => {
    document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key, shiftKey, isComposing, bubbles: true, cancelable: true }))
  })
  try {
    await act(async () => root.render(createElement(Form, { close })))
    await key('Tab')
    expect(document.activeElement).toBe(host.querySelector('input'))
    await key('Tab', true)
    expect(document.activeElement).toBe(host.querySelector('button:not(:disabled)'))
    await key('Tab')
    expect(document.activeElement).toBe(host.querySelector('input'))
    await key('Escape', false, true)
    expect(close).not.toHaveBeenCalled()
    await key('Escape')
    expect(close).toHaveBeenCalledOnce()
  } finally {
    await act(async () => root.unmount())
    expect(document.activeElement).toBe(opener)
    opener.remove(); host.remove()
  }
})
