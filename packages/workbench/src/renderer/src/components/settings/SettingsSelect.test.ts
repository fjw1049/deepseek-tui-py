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
