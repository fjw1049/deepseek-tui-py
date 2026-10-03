// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { TableDocumentPreview } from './TableDocumentPreview'
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
it('bounds table rows while allowing navigation through the preview', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(TableDocumentPreview, {
      path: 'table.csv', content: Array.from({ length: 150 }, (_, index) => `${index},value-${index}`).join('\n')
    })))
    expect(host.querySelectorAll('tbody tr')).toHaveLength(50)
    expect(host.textContent).not.toContain('value-100')
    const next = [...host.querySelectorAll('button')].find(button => button.textContent === 'workspaceTableNext')!
    await act(async () => next.click())
    await act(async () => next.click())
    expect(host.textContent).toContain('value-149')
    expect(host.querySelectorAll('tbody tr')).toHaveLength(50)
    expect(next.disabled).toBe(true)
  } finally { await act(async () => root.unmount()); host.remove() }
})
