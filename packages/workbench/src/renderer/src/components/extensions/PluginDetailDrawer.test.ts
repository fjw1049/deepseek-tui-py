// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { PluginDetailDrawer, type PluginRow } from './InstalledPluginsPanel'
vi.mock('./use-plugin-now', () => ({ usePluginNow: vi.fn() }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'zh' } }) }))

it('shows a concise introduction without reading rules without redundant management actions', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const readPluginRules = vi.fn()
  Object.assign(window, { dsGui: { readPluginRules } })
  const plugin: PluginRow = { name: 'data-analysis', version: '1', description: 'raw manifest description', path: '/private/plugin', scope: 'user', enabled: true, trusted: false, permissions: ['files'], components: { skills: true, rules: true, hooks: true, mcp_servers: false, commands: false, agents: false } }
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const onClose = vi.fn()
  try {
    await act(async () => root.render(createElement(PluginDetailDrawer, { detail: { kind: 'installed', key: 'user:data-analysis', plugin }, busy: false, installed: true, onClose })))
    expect(readPluginRules).not.toHaveBeenCalled()
    expect(host.querySelector('[role="dialog"]')).not.toBeNull()
    expect(host.textContent).toContain('pluginDataIntro')
    expect(host.textContent).toContain('pluginDataExample')
    expect(host.textContent).toContain('files')
    expect(host.textContent).not.toContain('/private/plugin')
    expect(host.textContent).not.toContain('pluginSysRemoveAction')
    expect(host.textContent).not.toContain('pluginManage')
    expect(host.textContent).not.toContain('pluginSysTrustAction')
    await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
    expect(onClose).toHaveBeenCalledOnce()
  } finally {
    await act(async () => root.unmount())
    host.remove()
  }
})
