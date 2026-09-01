// @vitest-environment happy-dom

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { GlassSegmentedControl } from './GlassSegmentedControl'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container: HTMLDivElement
let root: Root
let resizeCallback: ResizeObserverCallback | null

class FakeResizeObserver implements ResizeObserver {
  constructor(callback: ResizeObserverCallback) {
    resizeCallback = callback
  }

  disconnect(): void {}
  observe(): void {}
  unobserve(): void {}
}

beforeEach(() => {
  resizeCallback = null
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

describe('GlassSegmentedControl', () => {
  it('keeps the selection indicator on the committed value while another option is hovered', async () => {
    await act(async () => {
      root.render(
        createElement(GlassSegmentedControl, {
          value: 'light',
          ariaLabel: 'Theme preference',
          items: [
            { value: 'light', label: 'Light' },
            { value: 'dark', label: 'Dark' }
          ],
          onChange: vi.fn()
        })
      )
    })

    const [light, dark] = Array.from(container.querySelectorAll('button'))
    Object.defineProperties(light, {
      offsetLeft: { configurable: true, value: 4 },
      offsetWidth: { configurable: true, value: 80 }
    })
    Object.defineProperties(dark, {
      offsetLeft: { configurable: true, value: 88 },
      offsetWidth: { configurable: true, value: 80 }
    })
    await act(async () => resizeCallback?.([], {} as ResizeObserver))

    const thumb = container.querySelector<HTMLElement>('.ds-glass-segment-thumb')!
    expect(thumb.style.left).toBe('4px')

    await act(async () => {
      dark.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    })
    expect(thumb.style.left).toBe('4px')
  })

  it('exposes a keyboard-friendly radio group', async () => {
    const onChange = vi.fn()
    await act(async () => {
      root.render(
        createElement(GlassSegmentedControl, {
          value: 'light',
          ariaLabel: 'Theme preference',
          items: [
            { value: 'light', label: 'Light' },
            { value: 'dark', label: 'Dark' },
            { value: 'system', label: 'System' }
          ],
          onChange
        })
      )
    })

    const group = container.querySelector('[role="radiogroup"]')
    const radios = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="radio"]'))
    expect(group?.getAttribute('aria-label')).toBe('Theme preference')
    expect(radios.map((radio) => radio.getAttribute('aria-checked'))).toEqual([
      'true',
      'false',
      'false'
    ])
    expect(radios.map((radio) => radio.tabIndex)).toEqual([0, -1, -1])

    await act(async () => {
      radios[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
    })
    expect(onChange).toHaveBeenCalledWith('dark')
  })
})
