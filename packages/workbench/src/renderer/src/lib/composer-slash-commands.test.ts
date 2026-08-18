import { describe, expect, it } from 'vitest'

import {
  goalComposerSlashArgs,
  isGoalComposerSlashCommand,
  isUnknownComposerSlashCommand,
  parseComposerActionCommand,
  shouldCreateGoalFromComposer
} from './composer-slash-commands'

describe('composer slash commands', () => {
  it('parses action commands and arguments', () => {
    expect(parseComposerActionCommand('/model deepseek-v4-pro')).toEqual({
      id: 'model',
      args: 'deepseek-v4-pro'
    })
    expect(parseComposerActionCommand(' /MCP ')).toEqual({ id: 'mcp', args: '' })
  })

  it('does not claim normal text or mode commands', () => {
    expect(parseComposerActionCommand('hello')).toBeNull()
    expect(parseComposerActionCommand('/plan')).toBeNull()
    expect(isUnknownComposerSlashCommand('/not-real')).toBe(true)
  })

  it('does not classify Claude-style plugin commands as unknown', () => {
    expect(isUnknownComposerSlashCommand('/demo:hello')).toBe(false)
    expect(isUnknownComposerSlashCommand('/demo:hello world')).toBe(false)
  })

  it('treats /goal as a known sendable command', () => {
    expect(isGoalComposerSlashCommand('/goal')).toBe(true)
    expect(isGoalComposerSlashCommand('/goal pause')).toBe(true)
    expect(isUnknownComposerSlashCommand('/goal')).toBe(false)
    expect(isUnknownComposerSlashCommand('/goal Ship feature X')).toBe(false)
    expect(goalComposerSlashArgs('/goal Ship feature X')).toBe('Ship feature X')
    expect(goalComposerSlashArgs('/goal')).toBe('')
  })

  it('creates a goal from the first goal-mode message, including queued drains', () => {
    expect(shouldCreateGoalFromComposer('Ship feature X', 'goal', null)).toBe(true)
    expect(shouldCreateGoalFromComposer('Ship feature X', 'agent', null)).toBe(false)
    expect(shouldCreateGoalFromComposer('Ship feature X', 'goal', { status: 'active' })).toBe(
      false
    )
    expect(shouldCreateGoalFromComposer('/goal pause', 'goal', null)).toBe(false)
  })
})
