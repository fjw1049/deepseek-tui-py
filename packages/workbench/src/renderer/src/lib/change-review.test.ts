import { describe, expect, it } from 'vitest'
import { buildBranchComparisonOptions, normalizeChangeReviewRequest } from './change-review'

describe('normalizeChangeReviewRequest', () => {
  it('defaults to the full branch review', () => {
    expect(normalizeChangeReviewRequest(undefined)).toEqual({
      context: 'branch',
      turnId: undefined,
      path: undefined,
      workspaceRoot: undefined
    })
  })

  it('keeps a valid context and trims navigation context', () => {
    expect(
      normalizeChangeReviewRequest({
        context: 'last-turn',
        turnId: ' turn-1 ',
        path: ' src/a.ts ',
        workspaceRoot: ' /repo '
      })
    ).toEqual({
      context: 'last-turn',
      turnId: 'turn-1',
      path: 'src/a.ts',
      workspaceRoot: '/repo'
    })
  })

  it('supports Git and agent review scopes', () => {
    expect(normalizeChangeReviewRequest({ context: 'working-tree' }).context).toBe('working-tree')
    expect(normalizeChangeReviewRequest({ context: 'staged' }).context).toBe('staged')
    expect(normalizeChangeReviewRequest({ context: 'branch' }).context).toBe('branch')
    expect(normalizeChangeReviewRequest({ context: 'all-turns' }).context).toBe('all-turns')
  })

  it('maps the legacy project entry to the canonical project working tree', () => {
    expect(
      normalizeChangeReviewRequest({ context: 'project', workspaceRoot: ' /repo ' })
    ).toEqual({
      context: 'working-tree',
      turnId: undefined,
      path: undefined,
      workspaceRoot: '/repo'
    })
  })
})

describe('buildBranchComparisonOptions', () => {
  it('keeps the current branch selectable as a comparison base', () => {
    expect(
      buildBranchComparisonOptions({
        currentBranch: 'build_0831',
        defaultBranch: 'origin/main',
        branches: ['build_0831', 'build_0830', 'main']
      })
    ).toEqual({
      current: 'build_0831',
      default: 'origin/main',
      recent: ['build_0830'],
      searchable: ['build_0831', 'origin/main', 'build_0830']
    })
  })

  it('deduplicates the current and default branches from recent options', () => {
    expect(
      buildBranchComparisonOptions({
        currentBranch: 'main',
        defaultBranch: 'origin/main',
        branches: ['main', 'feature', 'feature']
      })
    ).toEqual({
      current: 'main',
      default: 'origin/main',
      recent: ['feature'],
      searchable: ['main', 'origin/main', 'feature']
    })
  })
})
