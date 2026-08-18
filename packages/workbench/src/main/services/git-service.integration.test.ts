import { execSync } from 'node:child_process'
import { describe, expect, it } from 'vitest'
import { getGitBranches, getGitHubRepository, getGitWorkingChanges } from './git-service'

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
})
