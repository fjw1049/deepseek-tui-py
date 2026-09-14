// @vitest-environment happy-dom
import { afterEach, expect, it } from 'vitest'
import './reasoning-effort-selector.js'

afterEach(() => { document.body.replaceChildren() })

it('lists models without search and supports keyboard navigation and selection', () => {
  const picker = document.createElement('reasoning-effort-selector') as HTMLElement & {
    models: { id: string; label: string }[]
  }
  document.body.append(picker)
  picker.models = ['one', 'two', 'three'].map(id => ({ id, label: id }))
  const root = picker.shadowRoot!
  expect(root.querySelector('input[type="search"]')).toBeNull()
  const rows = root.querySelectorAll<HTMLButtonElement>('.model-item')
  expect(rows).toHaveLength(3)
  rows[0].focus()
  rows[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
  expect(root.activeElement).toBe(rows[1])
  rows[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }))
  expect(root.activeElement).toBe(rows[0])
  const changes: unknown[] = []
  picker.addEventListener('change', event => changes.push((event as CustomEvent).detail))
  rows[1].click()
  expect(changes).toContainEqual({ type: 'model', id: 'two' })
})
