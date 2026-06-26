import { describe, expect, it } from 'vitest'
import {
  isExplicitGitCommitSelectionNone,
  resolveGitCommitPaths,
  syncGitCommitSelection
} from './git-commit-selection'

const ROOT = '/project'

describe('resolveGitCommitPaths', () => {
  it('defaults to all paths before selection is initialized', () => {
    expect(resolveGitCommitPaths([], ['a.ts', 'b.ts'], null, ROOT)).toEqual(['a.ts', 'b.ts'])
  })

  it('respects explicit empty selection after initialization', () => {
    expect(resolveGitCommitPaths([], ['a.ts', 'b.ts'], ROOT, ROOT)).toEqual([])
  })

  it('returns only selected paths that still exist', () => {
    expect(resolveGitCommitPaths(['a.ts'], ['a.ts', 'b.ts'], ROOT, ROOT)).toEqual(['a.ts'])
  })
})

describe('syncGitCommitSelection', () => {
  it('preserves selection during transient empty snapshots for the same workspace', () => {
    expect(syncGitCommitSelection(ROOT, ['a.ts'], ROOT, [])).toEqual({
      key: ROOT,
      paths: ['a.ts']
    })
  })

  it('selects all paths when workspace changes', () => {
    expect(syncGitCommitSelection('/old', ['a.ts'], ROOT, ['a.ts', 'b.ts'])).toEqual({
      key: ROOT,
      paths: ['a.ts', 'b.ts']
    })
  })

  it('re-selects all when previous selection was cleared but files returned', () => {
    expect(syncGitCommitSelection(ROOT, [], ROOT, ['a.ts'])).toEqual({
      key: ROOT,
      paths: ['a.ts']
    })
  })

  it('normalizes trailing slashes in workspace keys', () => {
    expect(syncGitCommitSelection(`${ROOT}/`, ['a.ts'], ROOT, ['a.ts'])).toEqual({
      key: ROOT,
      paths: ['a.ts']
    })
  })
})

describe('isExplicitGitCommitSelectionNone', () => {
  it('detects explicit select-none', () => {
    expect(isExplicitGitCommitSelectionNone(ROOT, [], ['a.ts'], ROOT)).toBe(true)
  })

  it('returns false before file list is known', () => {
    expect(isExplicitGitCommitSelectionNone(ROOT, [], [], ROOT)).toBe(false)
  })
})
