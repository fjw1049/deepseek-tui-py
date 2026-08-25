import { afterEach, describe, expect, it, vi } from 'vitest'
import { openWorkspaceFilePreferInApp, uniqueWorkspaceRoots } from './open-workspace-file'

describe('open workspace file prefer in-app', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('tries the in-app editor before VS Code', async () => {
    const openInApp = vi.fn(async () => true)
    const openEditorPath = vi.fn(async () => ({ ok: true, path: 'src/app.ts' }))
    vi.stubGlobal('window', {
      dsGui: { openEditorPath }
    })

    await expect(
      openWorkspaceFilePreferInApp({ path: 'src/app.ts', line: 4 }, '/proj', openInApp)
    ).resolves.toBe('in-app')
    expect(openInApp).toHaveBeenCalledWith('src/app.ts', '/proj', 4, undefined)
    expect(openEditorPath).not.toHaveBeenCalled()
  })

  it('tries the project root first, then the thread root', async () => {
    const openInApp = vi.fn(async (_path: string, root: string) => root === '/proj')
    const openEditorPath = vi.fn(async () => ({ ok: true, path: 'src/app.ts' }))
    vi.stubGlobal('window', {
      dsGui: { openEditorPath }
    })

    await expect(
      openWorkspaceFilePreferInApp({ path: 'src/app.ts' }, ['/tmp/session', '/proj'], openInApp)
    ).resolves.toBe('in-app')
    expect(openInApp).toHaveBeenNthCalledWith(1, 'src/app.ts', '/tmp/session', undefined, undefined)
    expect(openInApp).toHaveBeenNthCalledWith(2, 'src/app.ts', '/proj', undefined, undefined)
    expect(openEditorPath).not.toHaveBeenCalled()
  })

  it('opens VS Code only after every in-app attempt fails', async () => {
    const openInApp = vi.fn(async () => false)
    const openEditorPath = vi.fn(async () => ({ ok: true, path: '/other/a.ts' }))
    vi.stubGlobal('window', {
      dsGui: { openEditorPath }
    })

    await expect(
      openWorkspaceFilePreferInApp({ path: '/other/a.ts' }, '/proj', openInApp)
    ).resolves.toBe('external')
    expect(openInApp).toHaveBeenCalledWith('/other/a.ts', '/proj', undefined, undefined)
    expect(openEditorPath).toHaveBeenCalledWith(
      expect.objectContaining({
        path: '/other/a.ts',
        workspaceRoot: '/proj'
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
