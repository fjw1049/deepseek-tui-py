import { describe, expect, it } from 'vitest'
import {
  normalizeWorkspaceRoot,
  resolveActiveThreadWorkspace,
  resolveThreadFilesystemRoot,
  resolveThreadGitRoot
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

  it('uses the project path even when a managed worktree exists', () => {
    const threads = [
      {
        id: 't1',
        workspace: '/Users/me/proj',
        envMode: 'worktree' as const,
        worktreePath: '/Users/me/.deepseek/worktrees/proj-abc/thr_1'
      }
    ]
    expect(resolveActiveThreadWorkspace('t1', threads, '/Users/me/proj')).toBe('/Users/me/proj')
    expect(resolveThreadFilesystemRoot('t1', threads, '/Users/me/proj')).toBe('/Users/me/proj')
  })
})

describe('resolveThreadGitRoot', () => {
  it('uses the managed branch checkout without changing the visible project path', () => {
    const threads = [
      {
        id: 't1',
        workspace: '/Users/me/proj',
        envMode: 'worktree' as const,
        worktreePath: '/Users/me/.deepseek/worktrees/proj-abc/thr_1'
      }
    ]
    expect(resolveThreadFilesystemRoot('t1', threads, '/Users/me/proj')).toBe('/Users/me/proj')
    expect(resolveThreadGitRoot('t1', threads, '/Users/me/proj')).toBe(
      '/Users/me/.deepseek/worktrees/proj-abc/thr_1'
    )
  })

  it('falls back to the project checkout for local-mode tasks', () => {
    const threads = [{ id: 't1', workspace: '/Users/me/proj', envMode: 'local' as const }]
    expect(resolveThreadGitRoot('t1', threads, '/fallback')).toBe('/Users/me/proj')
  })

  it('switches roots with the active task instead of reusing the previous project', () => {
    const threads = [
      {
        id: 'myagent',
        workspace: '/Users/me/MyAgent',
        envMode: 'worktree' as const,
        worktreePath: '/Users/me/.deepseek/worktrees/MyAgent/thr_myagent'
      },
      {
        id: 'robotgo',
        workspace: '/Users/me/robotgo',
        envMode: 'worktree' as const,
        worktreePath: '/Users/me/.deepseek/worktrees/robotgo/thr_robotgo'
      }
    ]

    expect(resolveThreadGitRoot('robotgo', threads, '/Users/me/robotgo')).toBe(
      '/Users/me/.deepseek/worktrees/robotgo/thr_robotgo'
    )
    expect(resolveThreadGitRoot('myagent', threads, '/Users/me/MyAgent')).toBe(
      '/Users/me/.deepseek/worktrees/MyAgent/thr_myagent'
    )
  })
})
