// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { invalidateFileReferenceValidationCache, useValidatedFileReference } from './file-reference-validation'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

it('keeps settled links visible during refresh, applies deletion, and resets for a different target', async () => {
  const previousGui = window.dsGui
  type Result = Awaited<ReturnType<typeof window.dsGui.resolveWorkspaceFile>>
  let finish!: (value: Result) => void
  const resolveWorkspaceFile = vi.fn(() => new Promise<Result>((resolve) => { finish = resolve }))
  window.dsGui = { resolveWorkspaceFile } as unknown as typeof window.dsGui
  invalidateFileReferenceValidationCache()
  const host = document.createElement('div')
  const root = createRoot(host)
  const statuses: string[] = []
  function Probe({ path, workspace, revision }: { path: string; workspace: string; revision: number }) {
    const { validation } = useValidatedFileReference({ path }, workspace, revision)
    statuses.push(validation.status)
    return createElement('span', null, validation.status)
  }
  const render = async (path = 'a.ts', workspace = '/project', revision = 0) => {
    await act(async () => root.render(createElement(Probe, { path, workspace, revision })))
  }
  try {
    await render()
    expect(host.textContent).toBe('pending')
    await act(async () => finish({ ok: true, path: '/project/a.ts', kind: 'file' }))
    expect(host.textContent).toBe('valid')
    statuses.length = 0
    invalidateFileReferenceValidationCache()
    await render('a.ts', '/project', 1)
    expect(statuses).not.toContain('pending')
    expect(host.textContent).toBe('valid')
    await act(async () => finish({ ok: false, code: 'not_found', message: 'Removed' } as Result))
    expect(host.textContent).toBe('invalid')
    await render('b.ts')
    expect(host.textContent).toBe('pending')
    await act(async () => finish({ ok: true, path: '/project/b.ts', kind: 'file' }))
    statuses.length = 0
    await render('b.ts', '/other')
    expect(statuses.every((status) => status === 'pending')).toBe(true)
  } finally {
    await act(async () => root.unmount())
    window.dsGui = previousGui
    invalidateFileReferenceValidationCache()
  }
})
