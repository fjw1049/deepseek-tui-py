// @vitest-environment happy-dom
import { act } from 'react'
import { afterEach, expect, it } from 'vitest'
import { confirmAsync } from './confirm-dialog'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(() => { document.body.innerHTML = '' })

async function open(message: string, destructive = false) {
  let result!: Promise<boolean>
  await act(async () => { result = confirmAsync(message, { destructive }) })
  const dialog = document.querySelector<HTMLElement>('[role="alertdialog"]')!
  const buttons = [...dialog.querySelectorAll('button')]
  return { result, dialog, cancel: buttons[0]!, confirm: buttons[buttons.length - 1]! }
}

it('resolves true on confirm and removes the dialog', async () => {
  const { result, dialog, confirm } = await open('Delete this thread?')
  expect(dialog.getAttribute('aria-label')).toBe('Delete this thread?')
  await act(async () => confirm.click())
  await expect(result).resolves.toBe(true)
  expect(document.querySelector('[role="alertdialog"]')).toBeNull()
})

it('resolves false on cancel and on Escape', async () => {
  const first = await open('Remove?')
  await act(async () => first.cancel.click())
  await expect(first.result).resolves.toBe(false)
  const second = await open('Remove?')
  await act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })) })
  await expect(second.result).resolves.toBe(false)
  expect(document.querySelector('[role="alertdialog"]')).toBeNull()
})

it('splits the first paragraph into the title and keeps the rest as body', async () => {
  const { result, dialog, cancel } = await open('Review permissions\n\nWorkspace: /repo\nauto_approve: off → on', true)
  expect(dialog.getAttribute('aria-label')).toBe('Review permissions')
  expect(dialog.textContent).toContain('Workspace: /repo')
  await act(async () => cancel.click())
  await result
})
