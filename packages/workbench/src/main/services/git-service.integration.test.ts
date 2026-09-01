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
  pullGitBranch,
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

  it('returns exact staged and unstaged patches for a partially staged file', async () => {
    const repo = mkdtempSync(join(tmpdir(), 'deepseek-git-layers-'))
    const git = (...args: string[]): string =>
      execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim()
    try {
      git('init')
      git('config', 'user.name', 'Workbench Test')
      git('config', 'user.email', 'workbench@example.test')
      writeFileSync(join(repo, 'tracked.txt'), 'base\n')
      git('add', 'tracked.txt')
      git('commit', '-m', 'initial')
      writeFileSync(join(repo, 'tracked.txt'), 'staged version\n')
      git('add', 'tracked.txt')
      writeFileSync(join(repo, 'tracked.txt'), 'working version\n')

      const working = await getGitWorkingChanges(repo, 'working-tree')
      const staged = await getGitWorkingChanges(repo, 'staged')
      const unstaged = await getGitWorkingChanges(repo, 'unstaged')

      expect(working).toMatchObject({ ok: true, scope: 'working-tree' })
      expect(staged).toMatchObject({ ok: true, scope: 'staged' })
      expect(unstaged).toMatchObject({ ok: true, scope: 'unstaged' })
      if (!working.ok || !staged.ok || !unstaged.ok) return
      expect(working.files[0]?.stage).toBe('partial')
      expect(working.stagedFiles?.[0]?.patch).toContain('staged version')
      expect(working.unstagedFiles?.[0]?.patch).toContain('working version')
      expect(staged.files[0]?.patch).toContain('staged version')
      expect(staged.files[0]?.patch).not.toContain('working version')
      expect(unstaged.files[0]?.patch).toContain('working version')
    } finally {
      rmSync(repo, { recursive: true, force: true })
    }
  })

  it('commits the existing index when no explicit paths are supplied', async () => {
    const repo = mkdtempSync(join(tmpdir(), 'deepseek-git-index-commit-'))
    const git = (...args: string[]): string =>
      execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim()
    try {
      git('init')
      git('config', 'user.name', 'Workbench Test')
      git('config', 'user.email', 'workbench@example.test')
      writeFileSync(join(repo, 'staged.txt'), 'before\n')
      writeFileSync(join(repo, 'unstaged.txt'), 'before\n')
      git('add', 'staged.txt', 'unstaged.txt')
      git('commit', '-m', 'initial')
      writeFileSync(join(repo, 'staged.txt'), 'after\n')
      writeFileSync(join(repo, 'unstaged.txt'), 'after\n')
      git('add', 'staged.txt')

      const result = await commitGitChanges(repo, 'index only')
      expect(result).toMatchObject({ ok: true, fileCount: 1 })
      expect(git('show', '--pretty=', '--name-only', 'HEAD')).toBe('staged.txt')
      expect(git('status', '--porcelain')).toBe('M unstaged.txt')
    } finally {
      rmSync(repo, { recursive: true, force: true })
    }
  })

  it('compares a published feature branch against the repository base branch', async () => {
    const parent = mkdtempSync(join(tmpdir(), 'deepseek-git-branch-diff-'))
    const repo = join(parent, 'repo')
    const remote = join(parent, 'remote.git')
    const run = (cwd: string, ...args: string[]): string =>
      execFileSync('git', args, { cwd, encoding: 'utf8' }).trim()
    try {
      mkdirSync(repo)
      run(repo, 'init')
      run(repo, 'config', 'user.name', 'Workbench Test')
      run(repo, 'config', 'user.email', 'workbench@example.test')
      run(repo, 'branch', '-M', 'main')
      writeFileSync(join(repo, 'tracked.txt'), 'base\n')
      run(repo, 'add', 'tracked.txt')
      run(repo, 'commit', '-m', 'initial')
      run(parent, 'init', '--bare', remote)
      run(repo, 'remote', 'add', 'origin', remote)
      run(repo, 'push', '-u', 'origin', 'main')
      run(repo, 'switch', '-c', 'feature')
      writeFileSync(join(repo, 'tracked.txt'), 'feature\n')
      run(repo, 'add', 'tracked.txt')
      run(repo, 'commit', '-m', 'feature change')
      run(repo, 'push', '-u', 'origin', 'feature')

      const working = await getGitWorkingChanges(repo, 'working-tree')
      const branch = await getGitWorkingChanges(repo, 'branch')
      expect(working).toMatchObject({ ok: true, files: [] })
      expect(branch).toMatchObject({ ok: true, scope: 'branch', baseRef: 'origin/main' })
      if (!branch.ok) return
      expect(branch.files.map((file) => file.path)).toEqual(['tracked.txt'])
      expect(branch.files[0]?.patch).toContain('feature')
    } finally {
      rmSync(parent, { recursive: true, force: true })
    }
  })

  it('recommends the most recent ancestor and accepts an explicit comparison base', async () => {
    const repo = mkdtempSync(join(tmpdir(), 'deepseek-git-stacked-branches-'))
    const git = (...args: string[]): string =>
      execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim()
    const commitAt = (message: string, date: string): void => {
      execFileSync('git', ['commit', '-m', message], {
        cwd: repo,
        encoding: 'utf8',
        env: {
          ...process.env,
          GIT_AUTHOR_DATE: date,
          GIT_COMMITTER_DATE: date
        }
      })
    }
    try {
      git('init')
      git('config', 'user.name', 'Workbench Test')
      git('config', 'user.email', 'workbench@example.test')
      git('branch', '-M', 'main')
      writeFileSync(join(repo, 'base.txt'), 'base\n')
      git('add', 'base.txt')
      commitAt('base', '2026-08-29T10:00:00Z')

      git('switch', '-c', 'build_0830')
      writeFileSync(join(repo, 'previous.txt'), 'previous\n')
      git('add', 'previous.txt')
      commitAt('previous build', '2026-08-30T10:00:00Z')

      git('switch', '-c', 'build_0831')
      writeFileSync(join(repo, 'current.txt'), 'current\n')
      git('add', 'current.txt')
      commitAt('current build', '2026-08-31T10:00:00Z')

      const branches = await getGitBranches(repo)
      expect(branches).toMatchObject({
        ok: true,
        currentBranch: 'build_0831',
        detached: false,
        inferredBranch: null,
        defaultBranch: 'main',
        recommendedBase: 'build_0830'
      })
      if (!branches.ok) return
      expect(branches.branches.map((branch) => branch.name)).toEqual([
        'build_0831',
        'build_0830',
        'main'
      ])

      const automatic = await getGitWorkingChanges(repo, 'branch')
      expect(automatic).toMatchObject({ ok: true, baseRef: 'build_0830' })
      if (!automatic.ok) return
      expect(automatic.files.map((file) => file.path)).toEqual(['current.txt'])

      const againstMain = await getGitWorkingChanges(repo, 'branch', 'main')
      expect(againstMain).toMatchObject({ ok: true, baseRef: 'main' })
      if (!againstMain.ok) return
      expect(againstMain.files.map((file) => file.path)).toEqual([
        'current.txt',
        'previous.txt'
      ])

      writeFileSync(join(repo, 'draft.txt'), 'uncommitted\n')
      const againstCurrent = await getGitWorkingChanges(repo, 'branch', 'build_0831')
      expect(againstCurrent).toMatchObject({ ok: true, baseRef: 'build_0831' })
      if (!againstCurrent.ok) return
      expect(againstCurrent.files.map((file) => file.path)).toEqual(['draft.txt'])

      git('switch', '--detach')
      const detachedBranches = await getGitBranches(repo)
      expect(detachedBranches).toMatchObject({
        ok: true,
        currentBranch: null,
        detached: true,
        inferredBranch: 'build_0831',
        recommendedBase: 'build_0830'
      })
      const detachedChanges = await getGitWorkingChanges(repo, 'branch')
      expect(detachedChanges).toMatchObject({ ok: true, baseRef: 'build_0830' })
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

  it('pulls remote-only commits with fast-forward semantics', async () => {
    const parent = mkdtempSync(join(tmpdir(), 'deepseek-git-pull-'))
    const repo = join(parent, 'repo')
    const peer = join(parent, 'peer')
    const remote = join(parent, 'remote.git')
    const run = (cwd: string, ...args: string[]): string =>
      execFileSync('git', args, { cwd, encoding: 'utf8' }).trim()
    try {
      mkdirSync(repo)
      run(repo, 'init')
      run(repo, 'config', 'user.name', 'Workbench Test')
      run(repo, 'config', 'user.email', 'workbench@example.test')
      run(repo, 'branch', '-M', 'main')
      writeFileSync(join(repo, 'tracked.txt'), 'first\n')
      run(repo, 'add', 'tracked.txt')
      run(repo, 'commit', '-m', 'initial')
      run(parent, 'init', '--bare', remote)
      run(repo, 'remote', 'add', 'origin', remote)
      run(repo, 'push', '-u', 'origin', 'main')
      run(remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
      run(parent, 'clone', remote, peer)
      run(peer, 'config', 'user.name', 'Peer Test')
      run(peer, 'config', 'user.email', 'peer@example.test')
      writeFileSync(join(peer, 'tracked.txt'), 'from peer\n')
      run(peer, 'add', 'tracked.txt')
      run(peer, 'commit', '-m', 'peer update')
      run(peer, 'push')

      const result = await pullGitBranch(repo)
      expect(result).toMatchObject({ ok: true, branch: 'main', updated: true })
      expect(run(repo, 'show', '-s', '--format=%s', 'HEAD')).toBe('peer update')
    } finally {
      rmSync(parent, { recursive: true, force: true })
    }
  })

  it('refreshes remote refs before reporting ahead and behind state', async () => {
    const parent = mkdtempSync(join(tmpdir(), 'deepseek-git-refresh-'))
    const repo = join(parent, 'repo')
    const peer = join(parent, 'peer')
    const remote = join(parent, 'remote.git')
    const run = (cwd: string, ...args: string[]): string =>
      execFileSync('git', args, { cwd, encoding: 'utf8' }).trim()
    try {
      mkdirSync(repo)
      run(repo, 'init')
      run(repo, 'config', 'user.name', 'Workbench Test')
      run(repo, 'config', 'user.email', 'workbench@example.test')
      run(repo, 'branch', '-M', 'main')
      writeFileSync(join(repo, 'tracked.txt'), 'first\n')
      run(repo, 'add', 'tracked.txt')
      run(repo, 'commit', '-m', 'initial')
      run(parent, 'init', '--bare', remote)
      run(repo, 'remote', 'add', 'origin', remote)
      run(repo, 'push', '-u', 'origin', 'main')
      run(remote, 'symbolic-ref', 'HEAD', 'refs/heads/main')
      run(parent, 'clone', remote, peer)
      run(peer, 'config', 'user.name', 'Peer Test')
      run(peer, 'config', 'user.email', 'peer@example.test')
      writeFileSync(join(peer, 'tracked.txt'), 'from peer\n')
      run(peer, 'add', 'tracked.txt')
      run(peer, 'commit', '-m', 'peer update')
      run(peer, 'push')

      const stale = await getGitBranches(repo)
      expect(stale).toMatchObject({ ok: true, behind: 0 })

      const refreshed = await getGitBranches(repo, true)
      expect(refreshed).toMatchObject({ ok: true, ahead: 0, behind: 1 })
    } finally {
      rmSync(parent, { recursive: true, force: true })
    }
  })

  it('keeps local branch state available when a remote refresh fails', async () => {
    const repo = mkdtempSync(join(tmpdir(), 'deepseek-git-refresh-offline-'))
    const git = (...args: string[]): string =>
      execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim()
    try {
      git('init')
      git('config', 'user.name', 'Workbench Test')
      git('config', 'user.email', 'workbench@example.test')
      git('branch', '-M', 'main')
      writeFileSync(join(repo, 'tracked.txt'), 'first\n')
      git('add', 'tracked.txt')
      git('commit', '-m', 'initial')
      git('remote', 'add', 'origin', join(repo, 'missing-remote.git'))

      const result = await getGitBranches(repo, true)
      expect(result).toMatchObject({
        ok: true,
        currentBranch: 'main',
        hasRemote: true
      })
      if (!result.ok) return
      expect(result.remoteRefreshError).toMatch(/repository|remote|exist/i)
    } finally {
      rmSync(repo, { recursive: true, force: true })
    }
  })
})
