import { describe, expect, it } from 'vitest'
import {
  normalizeWorkspaceRoot,
  resolveActiveThreadWorkspace,
  resolveThreadFilesystemRoot
} from './workspace-path'

describe('resolveThreadFilesystemRoot', () => {
  it('keeps temporary thread workspaces that normalizeWorkspaceRoot blanks out', () => {
    const threads = [{ id: 't1', workspace: '/tmp/agent-run-123' }]
    expect(normalizeWorkspaceRoot('/tmp/agent-run-123')).toBe('')
    expect(resolveActiveThreadWorkspace('t1', threads, '/Users/me/proj')).toBe('/Users/me/proj')
    expect(resolveThreadFilesystemRoot('t1', threads, '/Users/me/proj')).toBe('/tmp/agent-run-123')
  })

  it('falls back to the settings workspace when the thread has none', () => {
    expect(resolveThreadFilesystemRoot('t1', [{ id: 't1' }], '/Users/me/proj')).toBe(
      '/Users/me/proj'
    )
  })
})
