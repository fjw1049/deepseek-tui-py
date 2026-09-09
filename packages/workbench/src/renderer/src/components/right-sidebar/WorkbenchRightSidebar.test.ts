// @vitest-environment happy-dom
import { act, createElement, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { WorkbenchRightSidebar } from './WorkbenchRightSidebar'
import { addRightSidebarTab, removeRightSidebarTab, type RightSidebarPanels } from '../../lib/right-sidebar-state'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, opts?: { name: string }) => opts ? `${key}:${opts.name}` : key }) }))
vi.mock('../../store/chat-store', () => ({ useChatStore: (select: (state: unknown) => unknown) => select({ activeThreadId: 'thread' }) }))
vi.mock('../../store/run-panel-store', () => ({ useRunPanelStore: (select: (state: unknown) => unknown) => select({ target: null }) }))
vi.mock('./RightSidebarCollapsedStrip', () => ({ RightSidebarCollapsedStrip: () => null }))
vi.mock('../AppTerminalPanel', () => ({ AppTerminalPanel: () => createElement('div', { 'data-terminal': '' }) }))
vi.mock('../workspace-editor/WorkspaceEditorPanel', () => ({ WorkspaceEditorPanel: () => createElement('div', null, 'file content') }))

globalThis.IS_REACT_ACT_ENVIRONMENT = true

it('opens from launcher, adds and reselects via menu, keeps terminal mounted, and closes back to launcher', async () => {
  function Harness() {
    const [state, setState] = useState<RightSidebarPanels>({ tabs: [], activeTab: null })
    return createElement(WorkbenchRightSidebar, {
      open: true, collapsed: false, tab: state.activeTab, tabs: state.tabs,
      onTabChange: (tab) => setState((s) => addRightSidebarTab(s, tab)),
      onCloseTab: (tab) => setState((s) => removeRightSidebarTab(s, tab)),
      width: 420, workspaceRoot: '', blocks: [], changesContext: 'branch',
      devPreviewBlocks: [], latestDevPreviewUrl: null,
      onChangesContextChange: vi.fn(), onToggleCollapsed: vi.fn(), onClose: vi.fn(),
      onToggleMaximize: vi.fn(), onBeginResize: vi.fn(), onOpenFileInEditor: vi.fn()
    })
  }
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const click = async (selector: string) => {
    const button = host.querySelector<HTMLButtonElement>(selector)
    expect(button).toBeTruthy()
    await act(async () => button!.click())
  }
  try {
    await act(async () => root.render(createElement(Harness)))
    expect(host.querySelectorAll('nav button')).toHaveLength(4)
    expect(host.querySelectorAll('[aria-pressed]')).toHaveLength(1) // maximize only
    await click('nav button:nth-child(3)') // terminal in existing function order
    const terminal = host.querySelector('[data-terminal]')
    expect(host.querySelector('nav')).toBeNull()
    await click('[aria-haspopup="menu"]')
    expect(document.activeElement?.getAttribute('role')).toBe('menuitem')
    await click('[role="menuitem"]') // files
    expect(host.textContent).toContain('file content')
    expect(host.querySelector('[data-terminal]')).toBe(terminal)
    await click('[aria-haspopup="menu"]')
    await click('[role="menuitem"]') // files again
    expect(host.querySelectorAll('[aria-label^="rightSidebarCloseTab:"]')).toHaveLength(2)
    await click('[aria-haspopup="menu"]')
    await act(async () => document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(host.querySelector('[role="menu"]')).toBeNull()
    expect(document.activeElement).toBe(host.querySelector('[aria-haspopup="menu"]'))
    await click('[aria-label="rightSidebarCloseTab:rightSidebarTabEditor"]')
    expect(host.querySelector('[data-terminal]')).toBe(terminal)
    await click('[aria-label="rightSidebarCloseTab:rightSidebarTabTerminal"]')
    expect(host.querySelectorAll('nav button')).toHaveLength(4)
  } finally {
    await act(async () => root.unmount())
    host.remove()
  }
})
