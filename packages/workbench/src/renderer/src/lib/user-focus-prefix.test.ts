import { describe, expect, it } from 'vitest'
import { isPluginControlOnlyMessage, parseUserFocusPrefix } from './user-focus-prefix'

describe('parseUserFocusPrefix', () => {
  it('parses plugin mount with body', () => {
    expect(parseUserFocusPrefix('@plugin:deepseek-dev 帮我分析')).toEqual({
      kind: 'plugin',
      name: 'deepseek-dev',
      body: '帮我分析'
    })
  })

  it('ignores plugin off/none control tokens', () => {
    expect(parseUserFocusPrefix('@plugin:off')).toBeNull()
    expect(parseUserFocusPrefix('@plugin:none')).toBeNull()
  })

  it('parses skill and connector prefixes', () => {
    expect(parseUserFocusPrefix('/data-extract go')).toEqual({
      kind: 'skill',
      name: 'data-extract',
      body: 'go'
    })
    expect(parseUserFocusPrefix('@github look here')).toEqual({
      kind: 'connector',
      name: 'github',
      body: 'look here'
    })
  })

  it('returns null for plain text', () => {
    expect(parseUserFocusPrefix('just a question')).toBeNull()
  })
})

describe('isPluginControlOnlyMessage', () => {
  it('detects mount/unmount-only wire text', () => {
    expect(isPluginControlOnlyMessage('@plugin:off')).toBe(true)
    expect(isPluginControlOnlyMessage('@plugin:warp')).toBe(true)
    expect(isPluginControlOnlyMessage('@plugin:warp do something')).toBe(false)
  })
})
