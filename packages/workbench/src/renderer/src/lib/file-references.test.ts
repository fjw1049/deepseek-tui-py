import { describe, expect, it } from 'vitest'
import { findFileReferences } from './file-references'

describe('findFileReferences', () => {
  it('linkifies absolute image paths written by agents', () => {
    const text =
      'Analysis charts were generated and saved successfully: /Users/fjw/.deepseek/workspace/scratch/analysis_charts.png (338,728 bytes).'
    const matches = findFileReferences(text)
    expect(matches).toHaveLength(1)
    expect(matches[0]?.target.path).toBe(
      '/Users/fjw/.deepseek/workspace/scratch/analysis_charts.png'
    )
  })

  it('linkifies bare filenames with known extensions', () => {
    expect(findFileReferences('created FileChip.tsx and notes.md today').map((m) => m.target.path)).toEqual([
      'FileChip.tsx',
      'notes.md'
    ])
    expect(findFileReferences('also wrote lib/app.ex and Main.kt').map((m) => m.target.path)).toEqual([
      'lib/app.ex',
      'Main.kt'
    ])
  })

  it('does not treat a basename inside a longer path as a second match', () => {
    expect(findFileReferences('see src/lib/file-chip.ts please').map((m) => m.target.path)).toEqual([
      'src/lib/file-chip.ts'
    ])
  })

  it('linkifies home and absolute directory paths', () => {
    expect(
      findFileReferences('check ~/.deepseek/agents/registries/ then continue').map((m) => m.target.path)
    ).toEqual(['~/.deepseek/agents/registries/'])
    expect(
      findFileReferences('also ~/.deepseek/agents/registries without slash').map((m) => m.target.path)
    ).toEqual(['~/.deepseek/agents/registries'])
  })

  it('recognizes common image extensions', () => {
    for (const ext of ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'JPG']) {
      const path = `/tmp/preview/chart.${ext}`
      const matches = findFileReferences(`see ${path} please`)
      expect(matches.map((m) => m.target.path)).toEqual([path])
    }
  })
})
