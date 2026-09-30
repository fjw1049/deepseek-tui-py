// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { GitChangeScope, GitWorkingChangesResult } from '@shared/git-working-changes'
import { useGitWorkingChanges } from './use-git-working-changes'

type Snapshot = ReturnType<typeof useGitWorkingChanges>
let host: HTMLDivElement
let root: Root
let previousGui: typeof window.dsGui
const latest = new Map<string, Snapshot>()
const requests: Array<(result: GitWorkingChangesResult) => void> = []
const read = vi.fn(() => new Promise<GitWorkingChangesResult>(resolve => requests.push(resolve)))
function Probe({ name, workspace, scope = 'branch', base }: { name: string; workspace: string; scope?: GitChangeScope; base?: string }) {
  const state = useGitWorkingChanges(workspace, scope, base)
  latest.set(name, state)
  return createElement('output', { 'data-probe': name }, state.result?.ok ? state.result.files.map(f => f.path).join(',') : '')
}
const result = (path: string): GitWorkingChangesResult => ({ ok: true, repositoryRoot: '/repo', scope: 'branch', files: [{ path, status: 'modified', stage: 'unstaged', patch: '@@ -1 +1 @@\n-old\n+new' }] })
const resolveRead = async (index: number, path: string) => act(async () => requests[index]!(result(path)))
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  previousGui = window.dsGui
  read.mockClear()
  requests.length = 0
  latest.clear()
  window.dsGui = { getGitWorkingChanges: read } as unknown as typeof window.dsGui
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  window.dsGui = previousGui
})

it('shares concurrent reads and refresh results without blanking visible contents', async () => {
  await act(async () => root.render(createElement('div', null,
    createElement(Probe, { name: 'list', workspace: '/sharing' }),
    createElement(Probe, { name: 'diff', workspace: '/sharing' })
  )))
  expect(read).toHaveBeenCalledTimes(1)
  await resolveRead(0, 'first.ts')
  expect(latest.get('list')!.result).toBe(latest.get('diff')!.result)
  await act(async () => { void latest.get('list')!.reload() })
  expect(read).toHaveBeenCalledTimes(2)
  expect(host.textContent).toBe('first.tsfirst.ts')
  expect(latest.get('diff')!.loading).toBe(true)
  await resolveRead(1, 'updated.ts')
  expect(host.textContent).toBe('updated.tsupdated.ts')
  await act(async () => root.render(createElement(Probe, { name: 'return', workspace: '/sharing' })))
  expect(host.textContent).toBe('updated.ts')
  await resolveRead(2, 'updated.ts')
})

it('isolates project, scope and comparison base, including late replies from a previous project', async () => {
  await act(async () => root.render(createElement(Probe, { name: 'view', workspace: '/previous' })))
  await act(async () => root.render(createElement('div', null,
    createElement(Probe, { name: 'view', workspace: '/current' }),
    createElement(Probe, { name: 'staged', workspace: '/current', scope: 'staged' }),
    createElement(Probe, { name: 'base', workspace: '/current', base: 'main' })
  )))
  expect(read).toHaveBeenCalledTimes(4)
  await resolveRead(0, 'wrong-project.ts')
  expect(host.textContent).toBe('')
  await resolveRead(1, 'current.ts')
  await resolveRead(2, 'staged.ts')
  await resolveRead(3, 'base.ts')
  expect(host.textContent).toBe('current.tsstaged.tsbase.ts')
})

it('reads again after a mutation during an in-flight read', async () => {
  await act(async () => root.render(createElement(Probe, { name: 'view', workspace: '/mutation' })))
  let refresh: Promise<void>
  await act(async () => { refresh = latest.get('view')!.reload(); void latest.get('view')!.reload() })
  expect(read).toHaveBeenCalledTimes(1)
  await resolveRead(0, 'before.ts')
  expect(read).toHaveBeenCalledTimes(2)
  expect(latest.get('view')!.loading).toBe(true)
  await resolveRead(1, 'after.ts')
  await refresh!
  expect(host.textContent).toBe('after.ts')
  expect(latest.get('view')!.loading).toBe(false)
})
