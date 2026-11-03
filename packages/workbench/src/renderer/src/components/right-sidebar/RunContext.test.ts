// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { RunContext } from './RunContext'
import type { ChatBlock } from '../../agent/types'
vi.mock('react-i18next', async (importOriginal) => ({ ...await importOriginal<typeof import('react-i18next')>(), useTranslation: () => ({ t: (key: string) => key }) }))
it('hides empty context, preserves manual collapse, and resets for another run', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const container = document.createElement('div')
  const root = createRoot(container)
  const render = async (id: string, blocks: ChatBlock[]) => {
    await act(async () => root.render(createElement(RunContext, { key: id, target: { threadId: 'parent', kind: 'task', id }, blocks })))
  }
  const blocks = (status: string): ChatBlock[] => [{ kind: 'tool', status: 'success', id: 'checklist', summary: 'checklist', meta: { tool_name: 'checklist', items: [{ id: 'one', content: 'Run-specific todo', status }] } }]
  try {
    await render('a', [])
    expect(container.querySelector('aside')).toBeNull()
    await render('a', blocks('in_progress'))
    expect(container.textContent).toContain('Run-specific todo')
    await act(async () => container.querySelector('button')!.click())
    await render('a', blocks('pending'))
    expect(container.querySelector('ul')).toBeNull()
    await render('b', blocks('pending'))
    expect(container.querySelector('ul')).not.toBeNull()
    await render('c', blocks('completed'))
    expect(container.querySelector('ul')).toBeNull()
    expect(container.textContent).toContain('1/1')
    await act(async () => container.querySelector('button')!.click())
    expect(container.textContent).toContain('Run-specific todo')
    await render('d', [])
    expect(container.querySelector('aside')).toBeNull()
  } finally {
    await act(async () => root.unmount())
    vi.unstubAllGlobals()
  }
})
