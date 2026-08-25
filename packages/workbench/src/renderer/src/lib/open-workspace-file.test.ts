import { afterEach, describe, expect, it, vi } from 'vitest'
import { openWorkspaceFilePreferInApp, uniqueWorkspaceRoots } from './open-workspace-file'

describe('open workspace file prefer in-app', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('opens in-app only when the file exists in the current project', async () => {
    const openInApp = vi.fn(async () => true)
    const openEditorPath = vi.fn(async () => ({ ok: true, path: 'src/app.ts' }))
    vi.stubGlobal('window', {
      dsGui: {
        resolveWorkspaceFile: vi.fn(async () => ({ ok: true, path: '/proj/src/app.ts' })),
        openEditorPath
      }
    })

    await expect(
      openWorkspaceFilePreferInApp({ path: 'src/app.ts', line: 4 }, '/proj', openInApp)
    ).resolves.toBe('in-app')
    expect(openInApp).toHaveBeenCalledWith('src/app.ts', '/proj', 4, undefined)
    expect(openEditorPath).not.toHaveBeenCalled()
  })

  it('opens VS Code without touching the in-app editor when the file is outside the project', async () => {
    const openInApp = vi.fn(async () => true)
    const openEditorPath = vi.fn(async () => ({ ok: true, path: '/other/a.ts' }))
    vi.stubGlobal('window', {
      dsGui: {
        resolveWorkspaceFile: vi.fn(async () => ({
          ok: false,
          message: 'Path must stay within the selected workspace'
        })),
        openEditorPath
      }
    })

    await expect(
      openWorkspaceFilePreferInApp({ path: '/other/a.ts' }, '/proj', openInApp)
    ).resolves.toBe('external')
    expect(openInApp).not.toHaveBeenCalled()
    expect(openEditorPath).toHaveBeenCalledWith(
      expect.objectContaining({
        path: '/other/a.ts',
        workspaceRoot: '/proj',
        allowOutsideWorkspace: true,
        searchRoots: ['/proj']
      })
    )
  })

  it('opens VS Code when the file is not in the current project', async () => {
    const openInApp = vi.fn(async () => true)
    const openEditorPath = vi.fn(async () => ({ ok: true, path: 'missing.ts' }))
    vi.stubGlobal('window', {
      dsGui: {
        resolveWorkspaceFile: vi.fn(async () => ({
          ok: false,
          message: 'File not found: missing.ts'
        })),
        openEditorPath
      }
    })

    await expect(
      openWorkspaceFilePreferInApp({ path: 'missing.ts' }, '/proj', openInApp)
    ).resolves.toBe('external')
    expect(openInApp).not.toHaveBeenCalled()
    expect(openEditorPath).toHaveBeenCalled()
  })

  it('passes extra roots so VS Code can open a file outside the current project', async () => {
    const openInApp = vi.fn(async () => true)
    const openEditorPath = vi.fn(async () => ({ ok: true, path: '/tmp/session/a.ts' }))
    vi.stubGlobal('window', {
      dsGui: {
        resolveWorkspaceFile: vi.fn(async () => ({ ok: false, message: 'File not found' })),
        openEditorPath
      }
    })

    await expect(
      openWorkspaceFilePreferInApp({ path: 'a.ts' }, '/proj', openInApp, ['/tmp/session'])
    ).resolves.toBe('external')
    expect(openInApp).not.toHaveBeenCalled()
    expect(openEditorPath).toHaveBeenCalledWith(
      expect.objectContaining({
        path: 'a.ts',
        allowOutsideWorkspace: true,
        searchRoots: ['/tmp/session', '/proj']
      })
    )
  })

  it('deduplicates workspace roots', () => {
    expect(uniqueWorkspaceRoots('/proj/', '/proj', '', '/tmp/session')).toEqual([
      '/proj/',
      '/tmp/session'
    ])
  })
})
