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
