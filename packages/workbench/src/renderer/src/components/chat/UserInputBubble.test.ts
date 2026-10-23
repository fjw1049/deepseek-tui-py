// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { UserInputBubble } from './UserInputBubble'
const { resolveUserInput } = vi.hoisted(() => ({ resolveUserInput: vi.fn().mockResolvedValue(undefined) }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../../store/chat-store', () => ({ useChatStore: (select: (s: { resolveUserInput: typeof resolveUserInput }) => unknown) => select({ resolveUserInput }) }))

it('accepts free text without choosing a fabricated option', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(UserInputBubble, { block: {
      kind: 'user_input', id: 'ask', requestId: 'ask', status: 'pending',
      questions: [{ id: 'order', header: 'Order', question: 'Order number?', options: [] }]
    } })))
    const input = host.querySelector('input')!
    expect(input).not.toBeNull()
    expect(host.textContent).not.toContain('userInputOtherDescription')
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    await act(async () => {
      setValue.call(input, '123')
      input.dispatchEvent(new Event('input', { bubbles: true }))
    })
    const submit = [...host.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.includes('userInputSubmit'))!
    expect(submit.disabled).toBe(false)
    await act(async () => submit.click())
    expect(resolveUserInput).toHaveBeenCalledWith('ask', { kind: 'submit', answers: [{ id: 'order', label: 'Other', value: '123' }] })
  } finally {
    await act(async () => root.unmount())
    host.remove()
  }
})

it('shows complete permission scope and submits only an explicit permission option', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  resolveUserInput.mockClear()
  const host = document.createElement('div')
  const root = createRoot(host)
  const question = 'Allow control of Notes?\nScope: this turn only. Read and edit documents.'
  try {
    await act(async () => root.render(createElement(UserInputBubble, { block: {
      kind: 'user_input', id: 'permission', requestId: 'permission', status: 'pending',
      questions: [{ id: 'cua_permission', header: 'Permission', question,
        options: [{ label: 'Allow once', value: 'allow_once', description: 'This turn' }] }]
    } })))
    expect(host.textContent).toContain(question)
    expect([...host.querySelectorAll('span')].find(s => s.textContent === question)?.className).not.toContain('truncate')
    expect(host.textContent).not.toContain('userInputOther')
    expect(host.querySelector('input')).toBeNull()
    const submit = [...host.querySelectorAll('button')].find(b => b.textContent === 'userInputSubmit')!
    expect(submit.disabled).toBe(true)
    await act(async () => [...host.querySelectorAll('button')].find(b => b.textContent?.includes('Allow once'))!.click())
    await act(async () => submit.click())
    expect(resolveUserInput).toHaveBeenCalledWith('permission', {
      kind: 'submit', answers: [{ id: 'cua_permission', label: 'Allow once', value: 'allow_once' }]
    })
  } finally { await act(async () => root.unmount()) }
})
