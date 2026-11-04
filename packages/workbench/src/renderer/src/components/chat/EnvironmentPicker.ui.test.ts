// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import i18n from '../../i18n'
import type { NormalizedThread } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'
import { EnvironmentPicker } from './EnvironmentPicker'

const initial = useChatStore.getState()
let container: HTMLDivElement
let root: Root

function thread(overrides: Partial<NormalizedThread> = {}): NormalizedThread {
  return {
    id: 'thread-a', title: 'A', createdAt: '', updatedAt: '', model: 'm', mode: 'agent',
    workspace: '/repo', envMode: 'worktree', ...overrides
  }
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  useChatStore.setState(initial, true)
})

describe('EnvironmentPicker', () => {
  it('explains each way the AI can edit files', async () => {
    useChatStore.setState({ activeThreadId: 'thread-a', threads: [thread()] })
    await act(async () => root.render(createElement(EnvironmentPicker, { workspaceRoot: '/repo' })))
    await act(async () => container.querySelector<HTMLButtonElement>('button')?.click())

    expect(container.textContent).toContain(i18n.t('envPickerLocalDescription'))
    expect(container.textContent).toContain(i18n.t('envPickerWorktreeDescription'))
  })

  it('says why the choice is locked once the chat has started', async () => {
    useChatStore.setState({ activeThreadId: 'thread-a', threads: [thread({ latestTurnId: 't1' })] })
    await act(async () => root.render(createElement(EnvironmentPicker, { workspaceRoot: '/repo' })))

    const trigger = container.querySelector<HTMLButtonElement>('button')!
    expect(trigger.disabled).toBe(true)
    expect(trigger.closest('[title]')?.getAttribute('title')).toBe(i18n.t('envPickerLockedHint'))
  })
})
