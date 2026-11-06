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

it('updates selected model effort without replacing rows or resetting scroll', () => {
  const picker = document.createElement('reasoning-effort-selector') as HTMLElement & {
    models: { id: string; label: string }[]
  }
  picker.setAttribute('model', 'one')
  picker.setAttribute('value', '2')
  document.body.append(picker)
  picker.models = ['one', 'two', 'three', 'four', 'five', 'six'].map(id => ({ id, label: id }))
  const root = picker.shadowRoot!
  const list = root.querySelector<HTMLElement>('.model-list')!
  const selected = root.querySelector('.model-item.is-active')!
  list.scrollTop = 38
  expect(selected.querySelector('.model-effort')?.textContent).toBe('High')
  root.querySelector('.slider')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }))
  expect(selected.querySelector('.model-effort')?.textContent).toBe('Extra High')
  expect(root.querySelector('.model-item.is-active')).toBe(selected)
  expect(list.scrollTop).toBe(38)
  expect(list.children).toHaveLength(6)
})

it('toggles effort on demand and keeps custom model configuration separate', () => {
  const picker = document.createElement('reasoning-effort-selector')
  document.body.append(picker)
  const root = picker.shadowRoot!
  const panel = root.querySelector<HTMLElement>('.intensity')!
  const effort = root.querySelector<HTMLButtonElement>('.effort-btn')!
  const configure = root.querySelector<HTMLButtonElement>('.configure-btn:not(.effort-btn)')!
  const pill = root.querySelector<HTMLButtonElement>('.pill')!
  const changes: unknown[] = []
  picker.addEventListener('change', event => changes.push((event as CustomEvent).detail))
  pill.click()
  expect(panel.hidden).toBe(true)
  effort.click()
  expect(panel.hidden).toBe(false)
  expect(effort.getAttribute('aria-expanded')).toBe('true')
  const slider = root.querySelector<HTMLElement>('.slider')!
  slider.focus()
  slider.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true, cancelable: true }))
  expect(root.activeElement).toBe(slider)
  expect(effort.title).toContain('Extra High')
  effort.click()
  expect(panel.hidden).toBe(true)
  effort.focus()
  effort.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true }))
  expect(root.activeElement).toBe(configure)
  effort.click()
  configure.click()
  expect(changes).toContainEqual({ type: 'configure-models' })
  pill.click()
  expect(panel.hidden).toBe(true)
})


it('does not retain a gray highlight after the pointer leaves a model', () => {
  const picker = document.createElement('reasoning-effort-selector') as HTMLElement & {
    models: { id: string; label: string }[]
  }
  document.body.append(picker)
  picker.models = [{ id: 'one', label: 'one' }, { id: 'two', label: 'two' }]
  const root = picker.shadowRoot!
  expect(root.querySelector('.is-highlight')).toBeNull()
  const row = root.querySelector('.model-item')!
  row.dispatchEvent(new PointerEvent('pointerenter'))
  row.dispatchEvent(new PointerEvent('pointerleave'))
  expect(root.querySelector('.is-highlight')).toBeNull()
})

it('shows the model name alone unless another endpoint uses the same name', () => {
  const picker = document.createElement('reasoning-effort-selector') as HTMLElement & {
    models: { id: string; label: string; compactLabel: string }[]
  }
  document.body.append(picker)
  picker.models = [
    { id: 'a', label: '众安/kimi-k3', compactLabel: 'kimi-k3' },
    { id: 'b', label: '众安/glm-5-3', compactLabel: 'glm-5-3' },
    { id: 'c', label: '备用/glm-5-3', compactLabel: 'glm-5-3' }
  ]
  const root = picker.shadowRoot!
  expect(Array.from(root.querySelectorAll('.model-label'), el => el.textContent))
    .toEqual(['kimi-k3', '众安/glm-5-3', '备用/glm-5-3'])
  expect(root.querySelector<HTMLButtonElement>('.model-item')?.title).toBe('众安/kimi-k3')
})
