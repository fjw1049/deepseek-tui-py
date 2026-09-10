import { describe, expect, it } from 'vitest'
import { compactRunTarget, groupRunActivity, runActionCount, runActionTargets, runDisplayTitle } from './run-activity'
import type { StepFlowItem } from '../components/chat/StepFlow'

describe('readable run activity', () => {
  it('groups narration with its actions and omits redundant lifecycle chrome', () => {
    const items: StepFlowItem[] = [
      { id: 'start', label: '● running', status: 'running' },
      { id: 'text', label: 'Read the code', status: 'info', variant: 'narration' },
      { id: 'read', label: 'Read', status: 'ok', toolName: 'read_file' },
      { id: 'next', label: 'Run the tests', status: 'info', variant: 'narration' }
    ]
    expect(groupRunActivity(items).map((group) => [group.id, group.actions.length])).toEqual([['text', 1], ['next', 0]])
  })
  it('uses domains and short paths without modifying the original detail', () => {
    const target = 'https://api.github.com/repos/example/project/git/trees/123456?recursive=1'
    const item: StepFlowItem = { id: 'web', label: 'Fetch', status: 'ok', variant: 'batch', batchCount: 3,
      batchEntries: [target, target, 'https://raw.githubusercontent.com/example/project/main/src/app.py'].map((url) => ({ toolName: 'fetch_url', kind: 'web', target: url })) }
    expect(runActionTargets(item)).toBe('api.github.com · raw.githubusercontent.com')
    expect(item.batchEntries![0].target).toBe(target)
    expect(compactRunTarget('/Users/example/project/src/app.py')).toBe('src/app.py')
    expect(runActionCount([item])).toBe(3)
  })
  it('keeps assignment boilerplate out of navigation titles', () => {
    expect(runDisplayTitle('分析代码库（根目录：/Users/example/project）')).toBe('分析代码库')
    expect(runDisplayTitle('Fix the parser (including edge cases)')).toBe('Fix the parser (including edge cases)')
  })
})
