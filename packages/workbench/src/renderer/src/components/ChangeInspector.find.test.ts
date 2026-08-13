import { describe, expect, it } from 'vitest'
import { findChangeItemId } from './ChangeInspector'

describe('findChangeItemId', () => {
  const items = [
    { id: 'a', filePath: 'src/foo.ts' },
    { id: 'b', filePath: 'src/Bar.TS' }
  ]

  it('matches a path case-insensitively', () => {
    expect(findChangeItemId(items, 'SRC/FOO.TS')).toBe('a')
  })

  it('normalizes backslashes', () => {
    expect(findChangeItemId(items, 'src\\Bar.ts')).toBe('b')
  })

  it('returns undefined when nothing matches', () => {
    expect(findChangeItemId(items, 'src/missing.ts')).toBeUndefined()
  })

  it('matches a workspace-absolute path to a relative inspector path', () => {
    expect(findChangeItemId(items, '/tmp/demo/src/foo.ts')).toBe('a')
  })
})
