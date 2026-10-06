// @vitest-environment happy-dom

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { SettingsSelect } from './SettingsSelect'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function renderSelect(onChange: ReturnType<typeof vi.fn>, allowReselect = false): void {
  root.render(
    createElement(
      SettingsSelect,
      {
        value: 'nord',
        onChange,
        allowReselect,
        'aria-label': 'Base theme'
      } as React.ComponentProps<typeof SettingsSelect> & { allowReselect: boolean },
      createElement('option', { value: 'nord' }, 'Nord'),
      createElement('option', { value: 'github' }, 'GitHub')
    )
  )
}

describe('SettingsSelect', () => {
  it('allows a theme picker to reapply the selected base theme', async () => {
    const onChange = vi.fn()
    await act(async () => renderSelect(onChange, true))

    const trigger = container.querySelector<HTMLButtonElement>('button')!
    await act(async () => trigger.click())
    const selected = document.body.querySelector<HTMLButtonElement>('[role="option"][aria-selected="true"]')!
    await act(async () => selected.click())

    expect(onChange).toHaveBeenCalledOnce()
    expect((onChange.mock.calls[0]?.[0] as { target: { value: string } }).target.value).toBe('nord')
  })

  it('closes an open popup when focus advances with Tab', async () => {
    await act(async () => renderSelect(vi.fn()))

    const trigger = container.querySelector<HTMLButtonElement>('button')!
    await act(async () => trigger.click())
    expect(document.body.querySelector('[role="listbox"]')).not.toBeNull()

    await act(async () => {
      trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))
    })

    expect(document.body.querySelector('[role="listbox"]')).toBeNull()
  })
})


it('skips disabled options with arrow keys and commits the highlighted enabled option', async () => {
  const onChange = vi.fn()
  await act(async () => root.render(createElement(SettingsSelect, { value: 'a', onChange },
    createElement('option', { value: 'a' }, 'A'),
    createElement('option', { value: 'b', disabled: true }, 'Unavailable'),
    createElement('option', { value: 'c' }, 'C')
  )))
  const trigger = container.querySelector<HTMLButtonElement>('[role="combobox"]')!
  await act(async () => trigger.click())
  await act(async () => trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })))
  expect(document.getElementById(trigger.getAttribute('aria-activedescendant')!)?.textContent).toBe('C')
  await act(async () => trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
  expect(onChange.mock.calls[0][0].target.value).toBe('c')
})

it('closes the menu when the control becomes disabled', async () => {
  const render = (disabled: boolean) => root.render(createElement(SettingsSelect, { value: 'a', disabled },
    createElement('option', { value: 'a' }, 'A')))
  await act(async () => render(false))
  await act(async () => container.querySelector<HTMLButtonElement>('button')!.click())
  expect(document.querySelector('[role="listbox"]')).not.toBeNull()
  await act(async () => render(true))
  expect(document.querySelector('[role="listbox"]')).toBeNull()
})

it('keeps the popup within a narrow viewport and chooses the roomier side', async () => {
  vi.stubGlobal('innerWidth', 300)
  vi.stubGlobal('innerHeight', 240)
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
    x: 180, y: 150, left: 180, top: 150, right: 380, bottom: 182, width: 200, height: 32,
    toJSON: () => ({})
  })
  await act(async () => renderSelect(vi.fn()))
  await act(async () => container.querySelector<HTMLButtonElement>('button')!.click())
  const menu = document.querySelector<HTMLElement>('[role="listbox"]')!
  expect(menu.style.left).toBe('88px')
  expect(menu.style.width).toBe('200px')
  expect(menu.style.bottom).toBe('96px')
  expect(menu.style.maxHeight).toBe('132px')
})
