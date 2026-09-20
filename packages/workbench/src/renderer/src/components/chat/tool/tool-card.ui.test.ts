// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { ToolCard } from './tool-card'
import { registerToolRenderers } from './renderers'
import { useDisclosureStore } from '../model/disclosure-store'
import { useChatStore } from '../../../store/chat-store'
import type { ToolBlock } from '../../../agent/types'

registerToolRenderers()
let container: HTMLDivElement
let root: Root
const initial = useChatStore.getState()
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  useDisclosureStore.setState({ disclosureById: {} })
  useChatStore.setState({ blocks: [], workspaceRoot: '' })
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  useChatStore.setState(initial, true)
  useDisclosureStore.setState({ disclosureById: {} })
})

const tools = ['read_file', 'edit_file', 'write_file', 'apply_patch', 'exec_shell', 'fetch_url', 'agent', 'plugin_tool']
it.each(tools)('%s stays collapsed across running, success and failure', async (toolName) => {
  for (const status of ['running', 'success', 'error'] as const) {
    const block: ToolBlock = {
      kind: 'tool', id: 'policy', summary: toolName, status,
      toolKind: ['edit_file', 'write_file', 'apply_patch'].includes(toolName) ? 'file_change' : toolName === 'exec_shell' ? 'command_execution' : undefined,
      detail: 'DETAIL_MUST_STAY_HIDDEN',
      meta: { tool_name: toolName, tool_input: { path: '/project/example.ts', command: 'echo example' } }
    }
    await act(async () => root.render(createElement(ToolCard, { block })))
    expect(container.querySelector('.ds-tool-row')).not.toBeNull()
    expect(container.querySelector('.ds-tool-header-row')?.textContent?.trim()).toBeTruthy()
    expect(container.querySelector('[role="button"]')?.getAttribute('aria-expanded')).toBe('false')
    expect(container.querySelector('.ds-tool-card')).toBeNull()
    expect(container.textContent).not.toContain('DETAIL_MUST_STAY_HIDDEN')
    expect(container.querySelector('pre')).toBeNull()
    expect(container.querySelector('[aria-label="error"]') !== null).toBe(status === 'error')
    expect(container.querySelector('[aria-label="success"]')).toBeNull()
  }
})

it('preserves an explicit choice across outcome changes and remounts', async () => {
  const block: ToolBlock = { kind: 'tool', id: 'choice', summary: 'plugin_tool', status: 'running', detail: 'USER_OPENED_DETAIL' }
  const render = async (status: ToolBlock['status']): Promise<void> => {
    await act(async () => root.render(createElement(ToolCard, { block: { ...block, status } })))
  }
  await render('running')
  await act(async () => (container.querySelector('[role="button"]') as HTMLElement).click())
  await render('error')
  expect(container.textContent).toContain('USER_OPENED_DETAIL')
  await act(async () => (container.querySelector('[role="button"]') as HTMLElement).click())
  await render('success')
  await act(async () => root.render(null))
  await render('running')
  expect(container.textContent).not.toContain('USER_OPENED_DETAIL')
})
