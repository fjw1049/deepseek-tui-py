import { execSync } from 'node:child_process'
import { describe, expect, it } from 'vitest'
import { getGitBranches, getGitWorkingChanges } from './git-service'

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
})
