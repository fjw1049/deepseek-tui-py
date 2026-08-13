import { describe, expect, it } from 'vitest'
import { appendComposerSnippet, formatComposerPathMention } from './composer-insert'

describe('formatComposerPathMention', () => {
  it('uses a bare @path for simple relative files', () => {
    expect(formatComposerPathMention('src/foo.ts')).toBe('@src/foo.ts')
  })

  it('quotes paths that contain spaces', () => {
    expect(formatComposerPathMention('src/my file.ts')).toBe('@"src/my file.ts"')
  })

  it('appends a line range when both ends differ', () => {
    expect(formatComposerPathMention('src/foo.ts', 12, 18)).toBe('@src/foo.ts:12-18')
  })

  it('appends a single line when the range collapses', () => {
    expect(formatComposerPathMention('src/foo.ts', 9, 9)).toBe('@src/foo.ts:9')
  })
})

describe('appendComposerSnippet', () => {
  it('replaces empty input', () => {
    expect(appendComposerSnippet('', '@src/foo.ts')).toBe('@src/foo.ts')
  })

  it('inserts a space before the snippet when needed', () => {
    expect(appendComposerSnippet('please review', '@src/foo.ts')).toBe('please review @src/foo.ts')
  })

  it('does not add a second space after trailing whitespace', () => {
    expect(appendComposerSnippet('please review ', '@src/foo.ts')).toBe('please review @src/foo.ts')
  })
})
