// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GoalSnapshotJson } from '../../agent/types'
import { GoalStrip } from './GoalStrip'

const state = vi.hoisted(() => ({
  goal: null as GoalSnapshotJson | null,
  command: vi.fn(async () => true)
}))

vi.mock('../../store/chat-store', () => ({
  useChatStore: (select: (s: { currentGoal: GoalSnapshotJson | null;
    applyGoalCommand: typeof state.command }) => unknown) => select({
      currentGoal: state.goal, applyGoalCommand: state.command
    })
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

describe('GoalStrip lifecycle controls', () => {
  let root: Root
  let host: HTMLDivElement
  beforeEach(() => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
    state.command.mockClear()
    host = document.createElement('div')
    document.body.append(host)
    root = createRoot(host)
  })
  afterEach(async () => {
    await act(async () => root.unmount())
    host.remove()
  })

  it('retains completed evidence and lets the user reopen', async () => {
    state.goal = { objective: 'Fix tests', status: 'complete', terminal_reason: 'Tests passed',
      completion_evidence: ['verify'], evidence: [
        { tool_call_id: 'verify', tool: 'exec_shell', description: 'pytest', success: true }
      ] }
    await act(async () => root.render(createElement(GoalStrip)))
    expect(host.textContent).toContain('Tests passed')
    expect(host.textContent).toContain('pytest')
    const reopen = [...host.querySelectorAll('button')]
      .find((button) => button.textContent === 'goalReopen')!
    await act(async () => reopen.click())
    expect(state.command).toHaveBeenCalledWith('reopen', { expectedGoalId: undefined })
  })

  it('requires a larger budget instead of presenting an ineffective resume button', async () => {
    state.goal = { goal_id: 'goal-1', objective: 'Fix tests', status: 'budget_limited',
      turns_used: 1, budget_limits: { turn_budget: 1 }, terminal_reason: 'Turn budget reached' }
    await act(async () => root.render(createElement(GoalStrip)))
    expect([...host.querySelectorAll('button')].some((b) => b.textContent === 'goalResume')).toBe(false)
    const input = host.querySelector<HTMLInputElement>('input')!
    expect(input.min).toBe('2')
    expect(input.value).toBe('1')
    expect(input.validity.valid).toBe(false)
    expect(state.command).not.toHaveBeenCalled()
  })

  it('shows unfinished work when paused', async () => {
    state.goal = { objective: 'Fix tests', status: 'paused', terminal_reason: 'No progress',
      checklist: [{ id: '1', content: 'Integration tests', status: 'pending' }] }
    await act(async () => root.render(createElement(GoalStrip)))
    expect(host.textContent).toContain('Integration tests')
    expect(host.textContent).toContain('0/1')
    expect([...host.querySelectorAll('button')].some((b) => b.textContent === 'goalResume')).toBe(true)
  })

  it('saves the edited budget before resuming', async () => {
    state.goal = { goal_id: 'goal-1', objective: 'Fix tests', status: 'budget_limited',
      turns_used: 1, budget_limits: { turn_budget: 1 } }
    await act(async () => root.render(createElement(GoalStrip)))
    const input = host.querySelector<HTMLInputElement>('input')!
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, '2')
      input.dispatchEvent(new Event('input', { bubbles: true }))
      input.dispatchEvent(new Event('change', { bubbles: true }))
    })
    await act(async () => host.querySelector<HTMLButtonElement>('button[type="submit"]')!.click())
    expect(state.command.mock.calls).toEqual([['budget turns 2', {
      expectedGoalId: 'goal-1', resumeAfterBudget: true
    }]])
  })

  it('shows acceptance requirements and their completion explanations', async () => {
    state.goal = { objective: 'Login', status: 'complete',
      requirements: [{ id: 'password', content: 'Reject wrong passwords' }],
      completion_audit: { checks: [{ requirement_id: 'password',
        explanation: 'Integration test confirms rejection', evidence: ['test'] }] } }
    await act(async () => root.render(createElement(GoalStrip)))
    expect(host.textContent).toContain('goalRequirements')
    expect(host.textContent).toContain('Reject wrong passwords')
    expect(host.textContent).toContain('Integration test confirms rejection')
  })
})
