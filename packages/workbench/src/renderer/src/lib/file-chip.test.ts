import { describe, expect, it } from 'vitest'
import {
  basenameOfPath,
  formatFileLineRange,
  looksLikeDirectoryPath,
  looksLikeFilePath,
  parseCodeFenceInfo,
  parseComposerPathMentions
} from './file-chip'

describe('file-chip helpers', () => {
  it('parses composer @path mentions with optional line ranges', () => {
    const text = 'see @src/foo.ts and @"src/my file.ts":12-18 please'
    expect(parseComposerPathMentions(text)).toEqual([
      { start: 4, end: 15, path: 'src/foo.ts' },
      { start: 20, end: 43, path: 'src/my file.ts', line: 12, endLine: 18 }
    ])
    expect(parseComposerPathMentions('@src/foo.ts:12-18 done')).toEqual([
      { start: 0, end: 17, path: 'src/foo.ts', line: 12, endLine: 18 }
    ])
  })

  it('ignores @plugin and bare aliases', () => {
    expect(parseComposerPathMentions('@plugin:demo look at @github')).toEqual([])
  })

  it('parses Cursor-style fence info without treating language as a path', () => {
    expect(parseCodeFenceInfo('173:186:src/lib/file-chip.ts')).toEqual({
      language: '',
      filePath: 'src/lib/file-chip.ts',
      lineStart: 173,
      lineEnd: 186
    })
    expect(parseCodeFenceInfo('typescript')).toEqual({ language: 'typescript' })
    expect(parseCodeFenceInfo('src/app.tsx')).toEqual({
      language: '',
      filePath: 'src/app.tsx'
    })
  })

  it('keeps basename and line labels compact', () => {
    expect(basenameOfPath('src/lib/foo.ts')).toBe('foo.ts')
    expect(formatFileLineRange(12)).toBe(':12')
    expect(formatFileLineRange(12, 18)).toBe(':12–18')
    expect(looksLikeFilePath('src/foo.ts')).toBe(true)
    expect(looksLikeFilePath('main.dart')).toBe(true)
    expect(looksLikeFilePath('github')).toBe(false)
    expect(looksLikeDirectoryPath('~/.deepseek/agents/registries/')).toBe(true)
    expect(looksLikeDirectoryPath('~/.deepseek/agents/registries')).toBe(true)
    expect(looksLikeDirectoryPath('src/foo.ts')).toBe(false)
  })
})
