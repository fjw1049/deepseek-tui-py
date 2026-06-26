import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mkdir, mkdtemp, realpath, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

vi.mock('electron', () => ({
  app: {
    getFileIcon: vi.fn()
  },
  shell: {
    openPath: vi.fn(),
    showItemInFolder: vi.fn()
  }
}))

import { readWorkspaceFile, resolveWorkspaceFile, listWorkspaceDirectory } from './workspace-service'

describe('workspace-service boundary checks', () => {
  let rootDir = ''
  let workspaceRoot = ''
  let outsideFile = ''

  beforeEach(async () => {
    rootDir = await mkdtemp(join(tmpdir(), 'ds-gui-workspace-'))
    workspaceRoot = join(rootDir, 'workspace')
    outsideFile = join(rootDir, 'outside.txt')
    await mkdir(workspaceRoot, { recursive: true })
    await writeFile(join(workspaceRoot, 'inside.txt'), 'inside', 'utf8')
    await writeFile(outsideFile, 'outside', 'utf8')
  })

  it('allows files inside the selected workspace', async () => {
    const result = await resolveWorkspaceFile({
      path: 'inside.txt',
      workspaceRoot
    })

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.path).toBe(await realpath(join(workspaceRoot, 'inside.txt')))
    }
  })

  it('rejects relative paths that escape the selected workspace', async () => {
    const result = await readWorkspaceFile({
      path: '../outside.txt',
      workspaceRoot
    })

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.message).toContain('within the selected workspace')
    }
  })

  it('rejects absolute paths outside the selected workspace', async () => {
    const result = await resolveWorkspaceFile({
      path: outsideFile,
      workspaceRoot
    })

    expect(result.ok).toBe(false)
    if (!result.ok) {
      expect(result.message).toContain('within the selected workspace')
    }
  })

  it('lists the workspace root directory', async () => {
    await mkdir(join(workspaceRoot, 'packages'), { recursive: true })
    await writeFile(join(workspaceRoot, 'packages', 'readme.txt'), 'hello', 'utf8')

    const result = await listWorkspaceDirectory(workspaceRoot, '')

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.entries.some((entry) => entry.name === 'inside.txt' && entry.kind === 'file')).toBe(
        true
      )
      expect(result.entries.some((entry) => entry.name === 'packages' && entry.kind === 'directory')).toBe(
        true
      )
    }
  })
})
