import { describe, expect, it } from 'vitest'
import { lookupPatchForPath, pathHasChanges } from './workspace-change-path'

describe('workspace-change-path', () => {
  it('matches nested workspace paths to git repo paths', () => {
    const map = new Map<string, string>([['packages/workbench/package.json', 'patch']])
    expect(lookupPatchForPath(map, 'package.json')).toBe('patch')
    expect(pathHasChanges(map, 'packages/workbench/package.json')).toBe(true)
  })
})
