// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { DefaultEditorPicker } from './DefaultEditorPicker'
import { readPreferredEditorId, writePreferredEditorId } from '../lib/editor-preferences'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../lib/editor-preferences', () => ({
  readPreferredEditorId: vi.fn(() => 'vscode'),
  writePreferredEditorId: vi.fn()
}))

it('uses the settings dropdown and saves the selected application', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const original = window.dsGui
  window.dsGui = {
    listEditors: vi.fn().mockResolvedValue({
      defaultEditorId: 'vscode',
      editors: [
        { id: 'vscode', label: 'VS Code', available: true, iconDataUrl: 'data:image/png;base64,AAAA' },
        { id: 'cursor', label: 'Cursor', available: true, iconDataUrl: 'data:image/png;base64,BBBB' },
        { id: 'system', label: 'System', available: true },
        { id: 'missing', label: 'Missing', available: false }
      ]
    })
  } as unknown as typeof window.dsGui
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  try {
    await act(async () => root.render(createElement(DefaultEditorPicker)))
    const trigger = container.querySelector<HTMLButtonElement>('[role="combobox"]')!
    expect(trigger.textContent).toBe('VS Code')
    expect(trigger.querySelector('img')?.getAttribute('src')).toBe('data:image/png;base64,AAAA')
    expect(trigger.parentElement?.classList.contains('w-full')).toBe(true)
    await act(async () => trigger.click())
    const menu = document.body.querySelector('[role="listbox"]')!
    expect(menu.parentElement).toBe(document.body)
    expect(menu.classList.contains('ds-settings-select-menu')).toBe(true)
    const options = Array.from(menu.querySelectorAll<HTMLButtonElement>('[role="option"]'))
    expect(options.map(option => option.textContent)).toEqual(['VS Code', 'Cursor'])
    expect(options[1].querySelector('img')?.getAttribute('src')).toBe('data:image/png;base64,BBBB')
    await act(async () => options[1].click())
    expect(writePreferredEditorId).toHaveBeenLastCalledWith('cursor')
    expect(trigger.textContent).toBe('Cursor')
    const icon = trigger.querySelector('img')!
    expect(icon.getAttribute('src')).toBe('data:image/png;base64,BBBB')
    await act(async () => icon.dispatchEvent(new Event('error')))
    expect(trigger.querySelector('img')).toBeNull()
    expect(trigger.querySelector('svg')).not.toBeNull()
    expect(document.body.querySelector('[role="listbox"]')).toBeNull()
    expect(readPreferredEditorId).toHaveBeenCalled()
  } finally {
    await act(async () => root.unmount())
    container.remove()
    window.dsGui = original
    vi.unstubAllGlobals()
  }
})
