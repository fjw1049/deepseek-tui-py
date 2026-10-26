// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ComposerPlusMenu, type ComposerPlusGroup } from './ComposerPlusMenu'
import '../../i18n'

const css = readFileSync(resolve(__dirname, 'composer-plus-menu.css'), 'utf8')

let host: HTMLDivElement
let style: HTMLStyleElement
let root: ReturnType<typeof createRoot>
const onClose = () => {}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  style = document.createElement('style')
  style.textContent = css
  document.head.append(style)
})

afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  style.remove()
  vi.restoreAllMocks()
})

it.each(['light', 'dark'])('uses customized %s colors for the menu and its rows', async theme => {
  host.setAttribute('data-theme', theme)
  host.style.cssText = '--ds-text: #123456; --ds-text-muted: #456789; --ds-surface-hover: #abcdef; --ds-surface-elevated: #fedcba;'
  const groups: ComposerPlusGroup[] = [{ id: 'test', label: 'Test', items: [
    { id: 'item', label: 'Item', description: 'Description', icon: null, onSelect: onClose }
  ] }]
  await act(async () => root.render(createElement(ComposerPlusMenu, { groups, onClose })))
  const computed = (selector: string) => getComputedStyle(host.querySelector(selector)!)
  expect(computed('[role="dialog"]').backgroundColor).toBe('#fedcba')
  expect(computed('[role="option"]').color).toBe('#123456')
  expect(computed('[role="option"]').backgroundColor).toBe('#abcdef')
  expect(computed('.ds-composer-plus-menu__description').color).toBe('#456789')
})

it('reserves the same panel height while first-load results arrive and focuses without scrolling', async () => {
  const focus = vi.spyOn(HTMLElement.prototype, 'focus')
  const groups: ComposerPlusGroup[] = [{ id: 'skills', label: 'Skills', loading: true, items: [] }]
  await act(async () => root.render(createElement(ComposerPlusMenu, { groups, onClose })))
  const height = () => getComputedStyle(host.querySelector('[role="dialog"]')!).height
  expect(height()).toBe('400px')
  expect(focus).toHaveBeenCalledWith({ preventScroll: true })
  await act(async () => root.render(createElement(ComposerPlusMenu, {
    groups: [{ ...groups[0], loading: false, items: Array.from({ length: 20 }, (_, index) => ({
      id: String(index), label: `Skill ${index}`, icon: null, onSelect: onClose
    })) }], onClose
  })))
  expect(height()).toBe('400px')
  expect(host.querySelectorAll('[role="option"]')).toHaveLength(20)
})
