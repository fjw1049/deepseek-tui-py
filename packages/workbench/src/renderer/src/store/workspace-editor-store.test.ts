import { describe, expect, it } from 'vitest'
import { normalizeEditorPathForTab } from './workspace-editor-store'

describe('normalizeEditorPathForTab', () => {
  it('preserves absolute POSIX paths from resolved file references', () => {
    expect(normalizeEditorPathForTab('/Users/fjw/Desktop/Tanzo-main/scratch/report.md')).toBe(
      '/Users/fjw/Desktop/Tanzo-main/scratch/report.md'
    )
  })

  it('normalizes separators without converting relative paths to absolute paths', () => {
    expect(normalizeEditorPathForTab('scratch\\report.md')).toBe('scratch/report.md')
  })
})
