import { describe, expect, it } from 'vitest'
import { parseUnifiedDiffForEditor } from './parse-unified-diff-for-editor'

describe('parseUnifiedDiffForEditor', () => {
  it('maps added and deleted hunks to editor line numbers', () => {
    const patch = [
      '--- a/README.md',
      '+++ b/README.md',
      '@@ -10,3 +10,4 @@',
      ' context',
      '-removed line',
      '+added line',
      ' context'
    ].join('\n')

    const result = parseUnifiedDiffForEditor(patch)
    expect(result.addedLines).toEqual([11])
    expect(result.deletionZones).toEqual([{ afterLineNumber: 10, text: 'removed line' }])
  })

  it('marks every line as added for a new file patch', () => {
    const patch = ['--- /dev/null', '+++ b/new.txt', '@@ -0,0 +1,2 @@', '+line one', '+line two'].join(
      '\n'
    )

    const result = parseUnifiedDiffForEditor(patch)
    expect(result.addedLines).toEqual([1, 2])
    expect(result.deletionZones).toEqual([])
  })

  it('does not skip added lines whose content starts with +++ or ---', () => {
    const patch = [
      '--- a/example.txt',
      '+++ b/example.txt',
      '@@ -1,1 +1,3 @@',
      ' context',
      '+++not a header',
      '+---also not a header',
      ' context'
    ].join('\n')

    const result = parseUnifiedDiffForEditor(patch)
    expect(result.addedLines).toEqual([2, 3])
    expect(result.deletionZones).toEqual([])
  })
})
