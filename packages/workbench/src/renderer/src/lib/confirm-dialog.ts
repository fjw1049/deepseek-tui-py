import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { ConfirmDialog } from '../components/workspace-editor/ConfirmDialog'
import i18n from 'i18next'

export type ConfirmOptions = {
  /** Deletes / irreversible actions render a red confirm button. */
  destructive?: boolean
}

/**
 * Promise-based in-app replacement for `window.confirm`. The native dialog is
 * synchronous: it freezes the renderer (streamed output stalls behind it) and
 * in Electron on Windows/Linux leaves the page unable to take keyboard input
 * until the window is refocused. A message's first paragraph becomes the
 * dialog title; any further paragraphs become its body.
 */
export function confirmAsync(message: string, options: ConfirmOptions = {}): Promise<boolean> {
  const [title = '', ...rest] = message.split(/\n{2,}/)
  const host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)
  return new Promise((resolve) => {
    let settled = false
    const settle = (value: boolean): void => {
      if (settled) return
      settled = true
      root.unmount()
      host.remove()
      resolve(value)
    }
    root.render(
      createElement(ConfirmDialog, {
        title,
        body: rest.length > 0 ? rest.join('\n\n') : undefined,
        confirmLabel: i18n.t('common:confirmAction'),
        cancelLabel: i18n.t('common:cancel'),
        destructive: options.destructive ?? false,
        onConfirm: () => settle(true),
        onCancel: () => settle(false)
      })
    )
  })
}
