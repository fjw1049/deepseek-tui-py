// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { PluginListItem } from './PluginListItem'
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

it('opens actions independently of details and invokes use or remove', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const onOpen = vi.fn(), onUse = vi.fn(), onRemove = vi.fn()
  try {
    await act(async () => root.render(createElement(PluginListItem, { pluginId: 'data-analysis', title: 'Data', summary: 'Analyze', onOpen, onUse, onRemove })))
    const menuButton = host.querySelector<HTMLButtonElement>('[aria-haspopup]')!
    await act(async () => menuButton.click())
    expect(onOpen).not.toHaveBeenCalled()
    expect(host.querySelector('[role="menu"]')).not.toBeNull()
    await act(async () => host.querySelector<HTMLButtonElement>('[role="menuitem"]')!.click())
    expect(onUse).toHaveBeenCalledOnce()
    expect(host.querySelector('[role="menu"]')).toBeNull()
    await act(async () => menuButton.click())
    await act(async () => host.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')[1].click())
    expect(onRemove).toHaveBeenCalledOnce()
    await act(async () => host.querySelector('button')!.click())
    expect(onOpen).toHaveBeenCalledOnce()
  } finally { await act(async () => root.unmount()); host.remove() }
})
