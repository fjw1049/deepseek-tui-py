import { useEffect, useRef, type RefObject } from 'react'

const stack: symbol[] = []

/** Keyboard focus for body-portaled form dialogs with native form controls. */
export function useModalFocus(open: boolean, panel: RefObject<HTMLElement | null>, onClose: () => void): void {
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    if (!open) return
    const id = Symbol()
    stack.push(id)
    const previous = document.activeElement as HTMLElement | null
    panel.current?.focus()
    const onKey = (event: KeyboardEvent): void => {
      if (stack.at(-1) !== id || event.isComposing || event.defaultPrevented) return
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        closeRef.current()
      }
      if (event.key !== 'Tab') return
      const root = panel.current
      const controls = Array.from(root?.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled):not([type="hidden"]), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])'
      ) ?? []).filter((node) => node.tabIndex >= 0 && !node.closest('[hidden], [inert]') &&
        getComputedStyle(node).display !== 'none' && getComputedStyle(node).visibility !== 'hidden')
      const first = controls[0]
      const last = controls.at(-1)
      if (!first || !root?.contains(document.activeElement) || document.activeElement === root ||
        (event.shiftKey ? document.activeElement === first : document.activeElement === last)) {
        event.preventDefault()
        ;((event.shiftKey ? last : first) ?? root)?.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      const wasTop = stack.at(-1) === id
      const index = stack.indexOf(id)
      if (index >= 0) stack.splice(index, 1)
      if (wasTop && previous?.isConnected) previous.focus()
    }
  }, [open, panel])
}
