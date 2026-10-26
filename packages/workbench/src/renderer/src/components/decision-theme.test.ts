// @vitest-environment happy-dom
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import postcss from 'postcss'
import tailwindcss from 'tailwindcss'
import loadConfig from 'tailwindcss/loadConfig'
import { afterEach, beforeAll, beforeEach, expect, it, vi } from 'vitest'
import { UserInputBubble } from './chat/UserInputBubble'
import { CuaPermissionsDialog } from './cua-preview/CuaPermissionsDialog'
import { ConfirmDialog } from './workspace-editor/ConfirmDialog'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../store/chat-store', () => ({ useChatStore: () => vi.fn() }))
let css: string
let host: HTMLDivElement
let style: HTMLStyleElement
let root: ReturnType<typeof createRoot>
let previousTheme: string | null
const noop = () => {}

// happy-dom does not resolve color-mix(); inspect generated utilities for these surfaces.
function expectThemeUtility(element: Element, className: string, property: string, token: string) {
  expect(element.classList.contains(className)).toBe(true)
  let value = ''
  postcss.parse(css).walkRules(`.${className}`, rule => {
    rule.walkDecls(property, declaration => { value = declaration.value })
  })
  expect(value).toContain(`var(${token})`)
}

beforeAll(async () => {
  const sources = ['chat/UserInputBubble.tsx', 'cua-preview/CuaPermissionsDialog.tsx', 'workspace-editor/ConfirmDialog.tsx']
  const config = loadConfig(resolve(__dirname, '../../../../tailwind.config.js'))
  const result = await postcss([tailwindcss({ ...config, content: sources.map(file => ({ raw: readFileSync(resolve(__dirname, file), 'utf8'), extension: 'tsx' })) })])
    .process('@tailwind utilities;', { from: undefined })
  css = result.css + readFileSync(resolve(__dirname, 'chat/user-input.css'), 'utf8')
})
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  previousTheme = document.documentElement.getAttribute('data-theme')
  style = document.createElement('style')
  style.textContent = css + ':root { --ds-surface-card: #e4decf; --ds-surface-hover: #cbbfa8; --ds-text: #243342; --ds-text-muted: #526374; --ds-danger: #ad2345; --ds-danger-soft: #f4dce3; }'
  document.head.append(style)
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  vi.stubGlobal('dsGui', {
    getCuaScreenPermission: vi.fn(async () => ({ status: 'denied', appName: 'Test' })),
    runtimeRequest: vi.fn(async () => ({ ok: true, body: '{"permissions":[]}' }))
  })
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove(); style.remove(); vi.unstubAllGlobals()
  if (previousTheme === null) document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', previousTheme)
})

it.each(['light', 'dark'])('uses custom %s colors for questions, selected answers and permission dialogs', async theme => {
  document.documentElement.setAttribute('data-theme', theme)
  await act(async () => root.render(createElement(UserInputBubble, { block: {
    kind: 'user_input', id: 'theme', requestId: 'theme', status: 'pending',
    questions: [{ id: 'q', header: 'Question', question: 'Choose', options: [{ label: 'One', value: 'one', description: '' }] }]
  } })))
  const card = host.querySelector('.ds-user-input-pending')!
  expect(getComputedStyle(card).backgroundColor).toBe('#e4decf')
  expect(getComputedStyle(card).color).toBe('#243342')
  const option = host.querySelector<HTMLButtonElement>('.ds-question-option')!
  await act(async () => option.click())
  expect(getComputedStyle(option).backgroundColor).toBe('#cbbfa8')
  await act(async () => root.render(createElement(CuaPermissionsDialog, { onClose: noop })))
  const dialog = document.querySelector('[role="dialog"]')!
  expectThemeUtility(dialog, 'bg-ds-card', 'background-color', '--ds-surface-card')
  expect(dialog.classList.contains('bg-white')).toBe(false)
  const button = [...dialog.querySelectorAll('button')].find(node => node.textContent === 'cuaPermissionCheck')!
  expectThemeUtility(button, 'bg-ds-card', 'background-color', '--ds-surface-card')
  expect(button.classList.contains('bg-white')).toBe(false)
})

it('uses the custom danger palette for destructive confirmation', async () => {
  await act(async () => root.render(createElement(ConfirmDialog, {
    title: 'Discard?', confirmLabel: 'Discard', cancelLabel: 'Cancel', destructive: true, onConfirm: noop, onCancel: noop
  })))
  const button = [...document.querySelectorAll('button')].find(node => node.textContent === 'Discard')!
  expectThemeUtility(button, 'bg-ds-danger-soft', 'background-color', '--ds-danger-soft')
  expectThemeUtility(button, 'text-ds-danger', 'color', '--ds-danger')
})
