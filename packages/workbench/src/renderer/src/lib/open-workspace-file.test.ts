import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  openWorkspaceFilePreferInApp,
  orderRootsForPath,
  uniqueWorkspaceRoots
} from './open-workspace-file'

describe('open workspace file prefer in-app', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('opens the first root that the in-app editor can load', async () => {
    const openInApp = vi.fn(async () => true)

    await expect(
      openWorkspaceFilePreferInApp({ path: 'src/app.ts', line: 4 }, '/proj', openInApp)
    ).resolves.toBe('in-app')
    expect(openInApp).toHaveBeenCalledWith('src/app.ts', '/proj', 4, undefined)
  })

  it('tries the thread root when the project root cannot open the file', async () => {
    const openInApp = vi.fn(async (_path: string, root: string) => root === '/tmp/session')

    await expect(
      openWorkspaceFilePreferInApp({ path: 'a.ts' }, ['/proj', '/tmp/session'], openInApp)
    ).resolves.toBe('in-app')
    expect(openInApp).toHaveBeenNthCalledWith(1, 'a.ts', '/proj', undefined, undefined)
    expect(openInApp).toHaveBeenNthCalledWith(2, 'a.ts', '/tmp/session', undefined, undefined)
  })

  it('does not open VS Code or Finder from the file-open path', async () => {
    const openInApp = vi.fn(async () => false)
    const openEditorPath = vi.fn(async () => ({ ok: true, path: 'src/app.ts' }))
    const showItemInFolder = vi.fn(async () => undefined)
    vi.stubGlobal('window', {
      dsGui: { openEditorPath, showItemInFolder }
    })

    await expect(
      openWorkspaceFilePreferInApp({ path: 'src/app.ts' }, '/proj', openInApp)
    ).resolves.toBe('none')
    expect(openEditorPath).not.toHaveBeenCalled()
    expect(showItemInFolder).not.toHaveBeenCalled()
  })

  it('prefers the workspace root that already contains an absolute file', () => {
    expect(
      orderRootsForPath('/proj/src/app.ts', ['/tmp/session', '/proj', '/proj/src'])
    ).toEqual(['/proj/src', '/proj', '/tmp/session'])
  })

  it('deduplicates workspace roots', () => {
    expect(uniqueWorkspaceRoots('/proj/', '/proj', '', '/tmp/session')).toEqual([
      '/proj/',
      '/tmp/session'
    ])
  })
})
