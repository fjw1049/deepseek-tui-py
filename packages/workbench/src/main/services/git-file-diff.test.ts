import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, it } from 'vitest'
import { getGitFileDiff, getGitWorkingChanges } from './git-service'
import { countDiffStats } from '../../renderer/src/lib/diff-stats'

it('reads every line from the correct staged, unstaged and branch versions for only the selected file', async () => {
  const repo = mkdtempSync(join(tmpdir(), 'deepseek-full-diff-'))
  const git = (...args: string[]) => execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim()
  const original = Array.from({ length: 60 }, (_, i) => `line${i}`)
  const write = (path: string, lines: string[]) => writeFileSync(join(repo, path), `${lines.join('\n')}\n`)
  try {
    git('init', '-b', 'main')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.test')
    mkdirSync(join(repo, 'src'))
    write('src/a[1].ts', original)
    write('src/a1.ts', original)
    git('add', '.')
    git('commit', '-m', 'initial')
    const staged = [...original]
    staged[25] = 'staged'
    write('src/a[1].ts', staged)
    git('add', '--', 'src/a[1].ts')
    const working = [...staged]
    working[40] = 'working'
    write('src/a[1].ts', working)
    write('src/a1.ts', ['unrelated'])
    for (const scope of ['staged', 'unstaged', 'working-tree', 'branch'] as const) {
      const full = await getGitFileDiff({ workspaceRoot: repo, path: 'src/a[1].ts', scope, baseRef: 'main' })
      expect(full.ok).toBe(true)
      if (!full.ok) continue
      expect(full.patch).toContain(' line0\n')
      expect(full.patch).toContain(' line59\n')
      expect(full.patch).not.toContain('unrelated')
      expect(full.patch).toContain(scope === 'unstaged' ? ' staged' : '+staged')
      expect(full.patch.includes('+working')).toBe(scope !== 'staged')
      const compact = await getGitWorkingChanges(repo, scope, 'main')
      expect(compact.ok).toBe(true)
      if (compact.ok) expect(countDiffStats(full.patch)).toEqual(countDiffStats(compact.files.find((file) => file.path === 'src/a[1].ts')!.patch))
    }
    write('new.ts', ['untracked'])
    const untracked = await getGitFileDiff({ workspaceRoot: repo, path: 'new.ts', scope: 'unstaged', untracked: true })
    expect(untracked.ok && untracked.patch).toContain('+untracked')
    git('rm', '-f', '--', 'src/a[1].ts')
    const deleted = await getGitFileDiff({ workspaceRoot: repo, path: 'src/a[1].ts', scope: 'staged' })
    expect(deleted.ok && deleted.patch).toContain('-line59')
    for (const path of ['', '../outside', '/outside', 'C:/outside']) {
      expect((await getGitFileDiff({ workspaceRoot: repo, path, scope: 'branch' })).ok).toBe(false)
    }
  } finally {
    rmSync(repo, { recursive: true, force: true })
  }
})

it('preserves rename stats and shows the full source even for a pure rename', async () => {
  const repo = mkdtempSync(join(tmpdir(), 'deepseek-rename-diff-'))
  const git = (...args: string[]) => execFileSync('git', args, { cwd: repo, encoding: 'utf8' }).trim()
  try {
    git('init', '-b', 'main')
    git('config', 'user.name', 'Test')
    git('config', 'user.email', 'test@example.test')
    const lines = Array.from({ length: 40 }, (_, i) => `source${i}`)
    writeFileSync(join(repo, 'old file.ts'), `${lines.join('\n')}\n`)
    git('add', '.')
    git('commit', '-m', 'initial')
    git('mv', 'old file.ts', 'new file.ts')
    writeFileSync(join(repo, 'new file.ts'), 'unstaged content\n')
    const target = { workspaceRoot: repo, path: 'new file.ts', oldPath: 'old file.ts', scope: 'staged' as const }
    const renamed = await getGitFileDiff(target)
    expect(renamed.ok && renamed.patch).toContain(' source39')
    expect(renamed.ok && renamed.patch).not.toContain('unstaged content')
    expect(renamed.ok && countDiffStats(renamed.patch)).toBeNull()
    lines[20] = 'modified'
    writeFileSync(join(repo, 'new file.ts'), `${lines.join('\n')}\n`)
    git('add', '.')
    const modified = await getGitFileDiff(target)
    expect(modified.ok && countDiffStats(modified.patch)).toEqual({ added: 1, removed: 1 })
    expect(modified.ok && modified.patch).toContain(' source39')
  } finally {
    rmSync(repo, { recursive: true, force: true })
  }
})
