import { describe, expect, it } from 'vitest'
import { isAuxiliaryWorkspaceEntry } from './workspace-tree-filter'

describe('workspace tree filtering', () => {
  it('hides generated directories and system metadata', () => {
    for (const name of ['.git', '.venv', '.pytest_cache', '.node_modules_trash_8078', 'node_modules']) {
      expect(isAuxiliaryWorkspaceEntry({ name, path: name, kind: 'directory' })).toBe(true)
    }
    expect(isAuxiliaryWorkspaceEntry({ name: '.DS_Store', path: '.DS_Store', kind: 'file' })).toBe(true)
  })
  it('keeps configuration and source files, including files named build', () => {
    for (const name of ['.env', '.gitignore', '.python-version', 'build', 'App.tsx']) {
      expect(isAuxiliaryWorkspaceEntry({ name, path: name, kind: 'file' })).toBe(false)
    }
    for (const name of ['.claude', '.idea', 'src']) {
      expect(isAuxiliaryWorkspaceEntry({ name, path: name, kind: 'directory' })).toBe(false)
    }
  })
})
