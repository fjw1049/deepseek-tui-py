import { describe, expect, it } from 'vitest'

import {
  isUnknownComposerSlashCommand,
  parseComposerActionCommand
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
})
