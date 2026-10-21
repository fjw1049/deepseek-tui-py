// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { AutomationResultCard } from './AutomationResultCard'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
it('expands the complete Markdown report and keeps runtime context in details', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(AutomationResultCard, { block: {
      kind: 'system', id: 'result', automation: { source: 'automation_result' },
      text: '[Daily report] ## Findings\n\n**Keep this**\n\n| File | Size |\n| --- | --- |\n| a.zip | 5 MB |\n\n任务要求：Inspect downloads\nTask ID: task_1\nRun ID: run_1'
    } })))
    expect(host.textContent).toContain('Daily report')
    expect(host.querySelector('h2')).toBeNull()
    expect(host.textContent).not.toContain('task_1')
    await act(async () => host.querySelector('button')!.click())
    expect(host.querySelector('button')!.getAttribute('aria-expanded')).toBe('true')
    expect(host.querySelector('h2')?.textContent).toBe('Findings')
    expect(host.querySelector('strong')?.textContent).toBe('Keep this')
    expect(host.querySelector('table')).not.toBeNull()
    expect(host.querySelector('.ds-markdown')!.textContent).not.toContain('Task ID')
    expect(host.querySelector('details')!.open).toBe(false)
    expect(host.querySelector('details')!.textContent).toContain('task_1')
    await act(async () => host.querySelector('button')!.click())
    expect(host.querySelector('h2')).toBeNull()
  } finally { await act(async () => root.unmount()) }
})
