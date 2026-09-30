import { expect, it } from 'vitest'
import { expandDiffContext } from './expand-diff-context'

it('fills leading, intermediate and trailing lines while preserving changes and line counts', () => {
  const patch = '@@ -2 +2 @@\n-old\n+new\n@@ -5,0 +6 @@\n+inserted'
  expect(expandDiffContext(patch, 'first\nnew\nthird\nfourth\nfifth\ninserted\nlast\n')).toBe(
    '@@ -1,6 +1,7 @@\n first\n-old\n+new\n third\n fourth\n fifth\n+inserted\n last'
  )
  expect(expandDiffContext('@@ -2 +1,0 @@\n-deleted', 'first\r\nlast\r\n')).toBe(
    '@@ -1,3 +1,2 @@\n first\n-deleted\n last'
  )
  expect(expandDiffContext('@@ -0,0 +1 @@\n+new', 'new\n')).toBe('@@ -0,0 +1,1 @@\n+new')
  expect(expandDiffContext('@@ -1 +0,0 @@\n-old', '')).toBe('@@ -1,1 +0,0 @@\n-old')
})

it('rejects outdated, truncated or unmappable patches instead of inventing unchanged lines', () => {
  expect(expandDiffContext('@@ -1 +1 @@\n-old\n+new', 'changed again\n')).toBeNull()
  expect(expandDiffContext('@@ -1,3 +1,3 @@\n same\n-old\n+new', 'same\nnew\nend\n')).toBeNull()
  expect(expandDiffContext('@@ -8 +8 @@\n-old\n+new', 'new\n')).toBeNull()
  expect(expandDiffContext('@@\n-old\n+new', 'new\n')).toBeNull()
})
