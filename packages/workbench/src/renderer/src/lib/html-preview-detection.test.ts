import { describe, expect, it } from 'vitest'
import type { ChatBlock, ToolBlock } from '../agent/types'
import {
  extractLatestTurnHtmlPreviewPaths,
  formatHtmlPreviewPathLabel,
  isRemoteUrlPath,
  selectOpenableTurnResults,
  selectPrimaryMarkdownResult
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

  it('ignores remote .html URLs from web_search tool dumps', () => {
    const blocks: ChatBlock[] = [
      { kind: 'user', id: 'u1', text: 'research kimi' },
      {
        kind: 'tool',
        id: 't1',
        toolKind: 'tool_call',
        status: 'success',
        summary: 'web_search: pricing',
        detail:
          '1. Kimi K3 定价\n   https://aicoding.csdn.net/6a5a062810ee7a33f28e7f37.html\n   pricing notes'
      },
      {
        kind: 'tool',
        id: 't2',
        toolKind: 'file_change',
        status: 'success',
        summary: 'wrote research_report_kimi3.md',
        filePath: '/Users/me/.deepseek/workspace/research_report_kimi3.md'
      }
    ]
    expect(extractLatestTurnHtmlPreviewPaths(blocks)).toEqual([])
  })

  it('still detects a real local html file_change', () => {
    const blocks: ChatBlock[] = [
      { kind: 'user', id: 'u1', text: 'ppt' },
      {
        kind: 'tool',
        id: 't1',
        toolKind: 'file_change',
        status: 'success',
        summary: 'edit frontend/index.html',
        filePath: '/Users/me/.deepseek/workspace/frontend/index.html'
      }
    ]
    expect(extractLatestTurnHtmlPreviewPaths(blocks)).toEqual([
      '/Users/me/.deepseek/workspace/frontend/index.html'
    ])
  })
})

describe('isRemoteUrlPath', () => {
  it('detects http(s) URLs', () => {
    expect(isRemoteUrlPath('https://aicoding.csdn.net/6a5a062810ee7a33f28e7f37.html')).toBe(
      true
    )
    expect(isRemoteUrlPath('http://example.com/a.html')).toBe(true)
    expect(isRemoteUrlPath('/tmp/a.html')).toBe(false)
    expect(isRemoteUrlPath('frontend/index.html')).toBe(false)
  })
})

describe('selectPrimaryMarkdownResult', () => {
  it('prefers research_report over earlier plan.md', () => {
    const changes: ToolBlock[] = [
      {
        kind: 'tool',
        id: 't1',
        toolKind: 'file_change',
        status: 'success',
        summary: 'plan',
        filePath: 'research_plan_kimi3.md'
      },
      {
        kind: 'tool',
        id: 't2',
        toolKind: 'file_change',
        status: 'success',
        summary: 'report',
        filePath: 'research_report_kimi3.md'
      }
    ]
    expect(selectPrimaryMarkdownResult(changes)?.filePath).toBe('research_report_kimi3.md')
  })

  it('returns the last md when no report/research name', () => {
    const changes: ToolBlock[] = [
      {
        kind: 'tool',
        id: 't1',
        toolKind: 'file_change',
        status: 'success',
        summary: 'a',
        filePath: 'notes.md'
      },
      {
        kind: 'tool',
        id: 't2',
        toolKind: 'file_change',
        status: 'success',
        summary: 'b',
        filePath: 'summary.md'
      }
    ]
    expect(selectPrimaryMarkdownResult(changes)?.filePath).toBe('summary.md')
  })
})

describe('selectOpenableTurnResults', () => {
  it('includes markdown and html, skips source edits', () => {
    const changes: ToolBlock[] = [
      {
        kind: 'tool',
        id: 't1',
        toolKind: 'file_change',
        status: 'success',
        summary: 'code',
        filePath: 'src/app.ts'
      },
      {
        kind: 'tool',
        id: 't2',
        toolKind: 'file_change',
        status: 'success',
        summary: 'note',
        filePath: 'random-note.md'
      },
      {
        kind: 'tool',
        id: 't3',
        toolKind: 'file_change',
        status: 'success',
        summary: 'page',
        filePath: 'out/index.html'
      }
    ]
    expect(selectOpenableTurnResults(changes)).toEqual([
      { path: 'out/index.html', kind: 'html' },
      { path: 'random-note.md', kind: 'markdown' }
    ])
  })

  it('prefers report names and later writes, caps at 4', () => {
    const changes: ToolBlock[] = [
      {
        kind: 'tool',
        id: 't1',
        toolKind: 'file_change',
        status: 'success',
        summary: 'a',
        filePath: 'a.md'
      },
      {
        kind: 'tool',
        id: 't2',
        toolKind: 'file_change',
        status: 'success',
        summary: 'b',
        filePath: 'b.md'
      },
      {
        kind: 'tool',
        id: 't3',
        toolKind: 'file_change',
        status: 'success',
        summary: 'c',
        filePath: 'c.md'
      },
      {
        kind: 'tool',
        id: 't4',
        toolKind: 'file_change',
        status: 'success',
        summary: 'report',
        filePath: 'research_report.md'
      },
      {
        kind: 'tool',
        id: 't5',
        toolKind: 'file_change',
        status: 'success',
        summary: 'd',
        filePath: 'd.md'
      },
      {
        kind: 'tool',
        id: 't6',
        toolKind: 'file_change',
        status: 'success',
        summary: 'rewrite',
        filePath: 'a.md'
      }
    ]
    expect(selectOpenableTurnResults(changes).map((item) => item.path)).toEqual([
      'research_report.md',
      'a.md',
      'd.md',
      'c.md'
    ])
  })

  it('skips failed writes and remote html urls', () => {
    const changes: ToolBlock[] = [
      {
        kind: 'tool',
        id: 't1',
        toolKind: 'file_change',
        status: 'error',
        summary: 'fail',
        filePath: 'broken.md'
      },
      {
        kind: 'tool',
        id: 't2',
        toolKind: 'file_change',
        status: 'success',
        summary: 'remote',
        filePath: 'https://example.com/a.html'
      }
    ]
    expect(selectOpenableTurnResults(changes)).toEqual([])
  })
})

describe('formatHtmlPreviewPathLabel', () => {
  it('returns the basename', () => {
    expect(formatHtmlPreviewPathLabel('/Users/me/proj/out/dashboard.html')).toBe('dashboard.html')
  })
})
