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

  it('recognizes common image extensions', () => {
    for (const ext of ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'JPG']) {
      const path = `/tmp/preview/chart.${ext}`
      const matches = findFileReferences(`see ${path} please`)
      expect(matches.map((m) => m.target.path)).toEqual([path])
    }
  })
})
