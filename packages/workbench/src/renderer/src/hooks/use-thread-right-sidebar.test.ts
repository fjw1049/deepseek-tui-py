// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { useThreadRightSidebar } from './use-thread-right-sidebar'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

it('restores the dock per thread and starts a new conversation closed without inherited panels', async () => {
  let dock!: ReturnType<typeof useThreadRightSidebar>
  function Harness({ threadId }: { threadId: string | null }) {
    dock = useThreadRightSidebar(threadId)
    return null
  }
  const root = createRoot(document.createElement('div'))
  const render = (threadId: string | null) => act(async () => root.render(createElement(Harness, { threadId })))
  try {
    await render('first')
    await act(async () => {
      dock.setOpen(true)
      dock.setPanels({ tabs: ['preview'], activeTab: 'preview' })
    })
    await render(null)
    expect(dock.open).toBe(false)
    expect(dock.panels.tabs).toEqual([])
    await render('second')
    expect(dock.open).toBe(false)
    await act(async () => {
      dock.setOpen(true)
      dock.setCollapsed(true)
      dock.setPanels({ tabs: ['terminal'], activeTab: 'terminal' })
    })
    await render('first')
    expect(dock.open).toBe(true)
    expect(dock.collapsed).toBe(false)
    expect(dock.panels).toEqual({ tabs: ['preview'], activeTab: 'preview' })
    await render('second')
    expect(dock.collapsed).toBe(true)
    expect(dock.panels.activeTab).toBe('terminal')
  } finally { await act(async () => root.unmount()) }
})
