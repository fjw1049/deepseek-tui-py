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

import {
  readWorkspaceFile,
  resolveWorkspaceFile,
  listWorkspaceDirectory,
  searchWorkspaceEntries,
  writePasteTextFile
} from './workspace-service'

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

  it('searches workspace files by path fragment', async () => {
    await mkdir(join(workspaceRoot, 'packages', 'core'), { recursive: true })
    await writeFile(join(workspaceRoot, 'packages', 'core', 'engine.ts'), 'export {}', 'utf8')
    await writeFile(join(workspaceRoot, 'packages', 'readme.txt'), 'hello', 'utf8')

    const result = await searchWorkspaceEntries(workspaceRoot, 'engine', 20)

    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.entries.some((entry) => entry.path === 'packages/core/engine.ts')).toBe(true)
      expect(result.entries.every((entry) => entry.kind === 'file')).toBe(true)
    }
  })

  it('writes a large paste as a workspace txt under .deepseek/pastes', async () => {
    const result = await writePasteTextFile({
      workspaceRoot,
      content: 'pasted dump'
    })

    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.relativePath.startsWith('.deepseek/pastes/paste-')).toBe(true)
    expect(result.name.endsWith('.txt')).toBe(true)
    expect(result.size).toBe(Buffer.byteLength('pasted dump', 'utf8'))
    const written = await readWorkspaceFile({
      path: result.relativePath,
      workspaceRoot
    })
    expect(written.ok).toBe(true)
    if (written.ok) {
      expect(written.content).toBe('pasted dump')
    }

    const second = await writePasteTextFile({
      workspaceRoot,
      content: 'second dump'
    })
    expect(second.ok).toBe(true)
    if (second.ok) {
      expect(second.relativePath).not.toBe(result.relativePath)
    }
  })

  it('rejects a paste write without a workspace root', async () => {
    const result = await writePasteTextFile({
      workspaceRoot: '',
      content: 'pasted dump'
    })
    expect(result.ok).toBe(false)
  })
})
