import { describe, expect, it } from 'vitest'
import { countDiffStats, resolvePatchStats, sumDiffStatsList } from './diff-stats'

const HUNK = [
  'diff --git a/foo.ts b/foo.ts',
  '--- a/foo.ts',
  '+++ b/foo.ts',
  '@@ -1,3 +1,4 @@',
  ' context',
  '-old',
  '+new1',
  '+new2'
].join('\n')

describe('countDiffStats', () => {
  it('counts only hunk body lines', () => {
    expect(countDiffStats(HUNK)).toEqual({ added: 2, removed: 1 })
  })

  it('counts hunk lines whose content starts with ++ or --', () => {
    const patch = [
      '--- a/foo',
      '+++ b/foo',
      '@@ -1,2 +1,2 @@',
      '--- dashdash',
      '+++ plusplus'
    ].join('\n')
    expect(countDiffStats(patch)).toEqual({ added: 1, removed: 1 })
  })

  it('returns null when the hunk has no line changes', () => {
    expect(countDiffStats('--- a/a\n+++ b/a\n@@\n context\n')).toBeNull()
  })
})

describe('resolvePatchStats / sumDiffStatsList', () => {
  it('prefers explicit counts over the patch', () => {
    expect(resolvePatchStats(HUNK, { added: 9, removed: 4 })).toEqual({
      added: 9,
      removed: 4
    })
  })

  it('falls back to the patch when explicit counts are zero', () => {
    expect(resolvePatchStats(HUNK, { added: 0, removed: 0 })).toEqual({
      added: 2,
      removed: 1
    })
  })

  it('sums the same per-file stats the list would show', () => {
    expect(
      sumDiffStatsList([
        { added: 6, removed: 3 },
        { added: 5, removed: 0 },
        { added: 2, removed: 0 }
      ])
    ).toEqual({ added: 13, removed: 3 })
  })
})
