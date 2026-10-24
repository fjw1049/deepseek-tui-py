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
    expect(host.querySelector('h3')?.textContent).toBe(question)
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


it('supports number keys, auto advance, backtracking and submits all answers once', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  vi.useFakeTimers()
  resolveUserInput.mockClear()
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(UserInputBubble, { block: {
      kind: 'user_input', id: 'multi', requestId: 'multi', status: 'pending',
      questions: [
        { id: 'role', header: 'Role', question: 'Your role?', options: [{ label: 'Engineer', value: 'engineer', description: '' }, { label: 'Designer', description: '' }] },
        { id: 'use', header: 'Use', question: 'Your use?', options: [{ label: 'Prototype', description: '' }] }
      ]
    } })))
    const card = host.querySelector<HTMLElement>('.ds-user-input-pending')!
    card.focus()
    await act(async () => card.dispatchEvent(new KeyboardEvent('keydown', { key: '1', bubbles: true })))
    expect(host.querySelector('[aria-pressed="true"]')?.textContent).toContain('Engineer')
    await act(async () => vi.advanceTimersByTime(240))
    expect(host.querySelector('h3')?.textContent).toBe('Your use?')
    const button = (text: string) => [...host.querySelectorAll('button')].find(b => b.textContent?.includes(text))!
    await act(async () => button('Prototype').click())
    expect(resolveUserInput).not.toHaveBeenCalled()
    await act(async () => button('userInputBack').click())
    expect(host.querySelector('[aria-pressed="true"]')?.textContent).toContain('Engineer')
    await act(async () => button('userInputNext').click())
    await act(async () => {
      button('userInputSubmit').click()
      button('userInputSubmit').click()
    })
    expect(resolveUserInput).toHaveBeenCalledTimes(1)
    expect(resolveUserInput).toHaveBeenCalledWith('multi', { kind: 'submit', answers: [
      { id: 'role', label: 'Engineer', value: 'engineer' },
      { id: 'use', label: 'Prototype', value: 'Prototype' }
    ] })
  } finally {
    await act(async () => root.unmount())
    host.remove()
    vi.useRealTimers()
  }
})

it('focuses custom answers, ignores number shortcuts in text, and respects IME composition', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  resolveUserInput.mockClear()
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(UserInputBubble, { block: {
      kind: 'user_input', id: 'custom', requestId: 'custom', status: 'pending',
      questions: [{ id: 'role', header: 'Role', question: 'Your role?', options: [{ label: 'Engineer', description: '' }] }]
    } })))
    const other = [...host.querySelectorAll('button')].find(b => b.textContent?.includes('userInputOther'))!
    other.focus()
    await act(async () => other.click())
    const input = host.querySelector('input')!
    expect(document.activeElement).toBe(input)
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!
    await act(async () => {
      setValue.call(input, 'Writer 123')
      input.dispatchEvent(new Event('input', { bubbles: true }))
      input.dispatchEvent(new KeyboardEvent('keydown', { key: '1', bubbles: true }))
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true }))
    })
    expect(resolveUserInput).not.toHaveBeenCalled()
    expect(input.value).toBe('Writer 123')
    await act(async () => input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
    expect(resolveUserInput).toHaveBeenCalledWith('custom', { kind: 'submit', answers: [{ id: 'role', label: 'Other', value: 'Writer 123' }] })
  } finally { await act(async () => root.unmount()); host.remove() }
})

it('locks selection and cancellation while a response is pending', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  resolveUserInput.mockClear()
  let finish!: () => void
  resolveUserInput.mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve }))
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(UserInputBubble, { block: {
      kind: 'user_input', id: 'cancel', requestId: 'cancel', status: 'pending',
      questions: [{ id: 'role', header: 'Role', question: 'Your role?', options: [{ label: 'Engineer', description: '' }] }]
    } })))
    const cancel = [...host.querySelectorAll('button')].find(b => b.textContent === 'userInputCancel')!
    await act(async () => { cancel.click(); cancel.click() })
    expect(resolveUserInput).toHaveBeenCalledTimes(1)
    expect([...host.querySelectorAll('button')].every(b => b.disabled)).toBe(true)
    expect(host.querySelector('[aria-busy="true"]')).not.toBeNull()
    await act(async () => finish())
    expect(cancel.disabled).toBe(false)
  } finally { await act(async () => root.unmount()) }
})
