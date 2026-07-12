import { describe, expect, it } from 'vitest'
import type { ChatBlock } from '../agent/types'
import {
  extractLatestTurnHtmlPreviewPaths,
  formatHtmlPreviewPathLabel
} from './html-preview-detection'

describe('extractLatestTurnHtmlPreviewPaths', () => {
  it('picks html paths from the latest turn file_change and assistant text', () => {
    const blocks: ChatBlock[] = [
      { kind: 'user', id: 'u0', text: 'old' },
      {
        kind: 'tool',
        id: 't0',
        toolKind: 'file_change',
        status: 'success',
        summary: 'wrote',
        filePath: '/old/report.html'
      },
      { kind: 'user', id: 'u1', text: 'make a dashboard' },
      {
        kind: 'tool',
        id: 't1',
        toolKind: 'file_change',
        status: 'success',
        summary: 'wrote out/dashboard.html',
        filePath: '/Users/me/proj/out/dashboard.html'
      },
      {
        kind: 'assistant',
        id: 'a1',
        text: 'Done. Open /Users/me/proj/out/dashboard.html'
      }
    ]

    expect(extractLatestTurnHtmlPreviewPaths(blocks)).toEqual([
      '/Users/me/proj/out/dashboard.html'
    ])
  })

  it('ignores earlier turns and non-html files', () => {
    const blocks: ChatBlock[] = [
      { kind: 'user', id: 'u1', text: 'hi' },
      {
        kind: 'tool',
        id: 't1',
        toolKind: 'file_change',
        status: 'success',
        summary: 'wrote',
        filePath: '/tmp/a.py'
      },
      { kind: 'assistant', id: 'a1', text: 'done' }
    ]
    expect(extractLatestTurnHtmlPreviewPaths(blocks)).toEqual([])
  })
})

describe('formatHtmlPreviewPathLabel', () => {
  it('returns the basename', () => {
    expect(formatHtmlPreviewPathLabel('/Users/me/proj/out/dashboard.html')).toBe('dashboard.html')
  })
})
