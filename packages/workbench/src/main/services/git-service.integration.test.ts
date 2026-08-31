import { execFileSync, execSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  getGitBranches,
  getGitHubRepository,
  getGitWorkingChanges,
  commitGitChanges,
  pushGitBranch,
  stageGitChanges,
  unstageGitChanges
} from './git-service'

const REPO_ROOT = execSync('git rev-parse --show-toplevel', { encoding: 'utf8' }).trim()

describe('git-service integration', () => {
  it('getGitWorkingChanges returns files when branches report dirty count', async () => {
    const branches = await getGitBranches(REPO_ROOT)
    expect(branches.ok).toBe(true)
    if (!branches.ok) return

    const changes = await getGitWorkingChanges(REPO_ROOT)
    expect(changes.ok).toBe(true)
    if (!changes.ok) return

    if (branches.dirtyCount > 0) {
      expect(changes.files.length).toBeGreaterThan(0)
    }
  })

  it('getGitHubRepository resolves this repo from origin when it is GitHub', async () => {
    const result = await getGitHubRepository(REPO_ROOT)
    if (!result.ok) {
      expect(['no_github_remote', 'not_git_repo', 'git_unavailable']).toContain(result.reason)
      return
    }
    expect(result.nameWithOwner).toMatch(/^[^/]+\/[^/]+$/)
    expect(result.url).toBe(`https://github.com/${result.nameWithOwner}`)
  })

  it('getGitHubRepository reports no workspace', async () => {
    const result = await getGitHubRepository('   ')
    expect(result).toEqual({
      ok: false,
      reason: 'no_workspace',
      message: 'No working directory selected.'
    })
  })

  it('stages and unstages only the selected paths', async () => {
    const repo = mkdtempSync(join(tmpdir(), 'deepseek-git-actions-'))
    const git = (...args: string[]): string =>
      execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim()
    try {
      git('init')
      git('config', 'user.name', 'Workbench Test')
      git('config', 'user.email', 'workbench@example.test')
      writeFileSync(join(repo, 'tracked.txt'), 'before\n')
      git('add', 'tracked.txt')
      git('commit', '-m', 'initial')
      writeFileSync(join(repo, 'tracked.txt'), 'after\n')

      const staged = await stageGitChanges(repo, ['tracked.txt'])
      expect(staged).toMatchObject({ ok: true, fileCount: 1 })
      expect(git('diff', '--cached', '--name-only')).toBe('tracked.txt')

      const unstaged = await unstageGitChanges(repo, ['tracked.txt'])
      expect(unstaged).toMatchObject({ ok: true, fileCount: 1 })
      expect(git('diff', '--cached', '--name-only')).toBe('')
      expect(git('diff', '--name-only')).toBe('tracked.txt')
    } finally {
      rmSync(repo, { recursive: true, force: true })
    }
  })

  it('commits selected paths without consuming other staged changes', async () => {
    const repo = mkdtempSync(join(tmpdir(), 'deepseek-git-commit-selection-'))
    const git = (...args: string[]): string =>
      execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim()
    try {
      git('init')
      git('config', 'user.name', 'Workbench Test')
      git('config', 'user.email', 'workbench@example.test')
      writeFileSync(join(repo, 'selected.txt'), 'before\n')
      writeFileSync(join(repo, 'other.txt'), 'before\n')
      git('add', 'selected.txt', 'other.txt')
      git('commit', '-m', 'initial')
      writeFileSync(join(repo, 'selected.txt'), 'selected after\n')
      writeFileSync(join(repo, 'other.txt'), 'other after\n')
      git('add', 'other.txt')

      const result = await commitGitChanges(repo, 'selected update', ['selected.txt'])
      expect(result).toMatchObject({ ok: true, fileCount: 1 })
      expect(git('show', '--pretty=', '--name-only', 'HEAD')).toBe('selected.txt')
      expect(git('diff', '--cached', '--name-only')).toBe('other.txt')
    } finally {
      rmSync(repo, { recursive: true, force: true })
    }
  })

  it('publishes a branch to a local remote and reports ahead state', async () => {
    const parent = mkdtempSync(join(tmpdir(), 'deepseek-git-push-'))
    const repo = join(parent, 'repo')
    const remote = join(parent, 'remote.git')
    const run = (cwd: string, ...args: string[]): string =>
      execFileSync('git', args, { cwd, encoding: 'utf8' }).trim()
    try {
      mkdirSync(repo)
      run(repo, 'init')
      run(repo, 'config', 'user.name', 'Workbench Test')
      run(repo, 'config', 'user.email', 'workbench@example.test')
      writeFileSync(join(repo, 'tracked.txt'), 'first\n')
      run(repo, 'add', 'tracked.txt')
      run(repo, 'commit', '-m', 'initial')
      run(parent, 'init', '--bare', remote)
      run(repo, 'remote', 'add', 'origin', remote)

      const firstPush = await pushGitBranch(repo)
      expect(firstPush).toMatchObject({ ok: true, pushed: true })

      writeFileSync(join(repo, 'tracked.txt'), 'second\n')
      run(repo, 'add', 'tracked.txt')
      run(repo, 'commit', '-m', 'second')
      const beforePush = await getGitBranches(repo)
      expect(beforePush).toMatchObject({ ok: true, ahead: 1, behind: 0 })

      const secondPush = await pushGitBranch(repo)
      expect(secondPush).toMatchObject({ ok: true, pushed: true })
      const afterPush = await getGitBranches(repo)
      expect(afterPush).toMatchObject({ ok: true, ahead: 0, behind: 0 })
    } finally {
      rmSync(parent, { recursive: true, force: true })
    }
  })
})
