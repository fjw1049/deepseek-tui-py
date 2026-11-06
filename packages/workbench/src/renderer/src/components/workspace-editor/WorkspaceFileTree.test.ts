// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { WorkspaceFileTree } from './WorkspaceFileTree'
import { readExpandedDirs, writeExpandedDirs } from '../../lib/workspace-file-tree-expand-cache'
import { useWorkspaceViewPreferences } from '../../store/workspace-view-preferences'
import type { WorkspaceTreeEntry } from '@shared/workspace-file'

const { t } = vi.hoisted(() => ({ t: (key: string) => key }))
vi.mock('react-i18next', async (original) => ({ ...await original<typeof import('react-i18next')>(), useTranslation: () => ({ t }) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const dir = (path: string): WorkspaceTreeEntry => ({ name: path.split('/').at(-1)!, path, kind: 'directory' })
const file = (path: string): WorkspaceTreeEntry => ({ name: path.split('/').at(-1)!, path, kind: 'file' })
const result = (entries: WorkspaceTreeEntry[]) => ({ ok: true as const, path: '', entries })
let host: HTMLDivElement
let root: Root
let workspace: string
let sequence = 0
const previousGui = window.dsGui
beforeEach(() => {
  workspace = `/tree-test-${++sequence}`
  useWorkspaceViewPreferences.setState({ showAllFiles: false })
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})
afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  window.dsGui = previousGui
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
async function mount(list: (...args: any[]) => any, onOpenFile = vi.fn(), path = workspace) {
  window.dsGui = { listWorkspaceDirectory: list } as unknown as typeof window.dsGui
  await act(async () => root.render(createElement(WorkspaceFileTree, { workspaceRoot: path, onOpenFile })))
}
async function click(label: string) {
  await act(async () => host.querySelector<HTMLButtonElement>(`[aria-label="${label}"]`)!.click())
}
async function flush() {
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 30)) })
}

it('keeps 20,200 rows virtual, opens scrolled files and refreshes only root after collapse', async () => {
  const list = vi.fn(async (_root: string, path: string) => result(path
    ? Array.from({ length: 100 }, (_, i) => file(`${path}/f${i}.py`))
    : Array.from({ length: 200 }, (_, i) => dir(`dir${i}`))))
  const open = vi.fn()
  await mount(list, open)
  const storage = vi.spyOn(window.localStorage, 'setItem')
  await click('workspaceTreeExpandAll')
  for (let i = 0; i < 30 && list.mock.calls.length < 201; i += 1) await flush()
  await flush()
  expect(list).toHaveBeenCalledTimes(201)
  expect(host.querySelectorAll('.ds-workspace-file-tree__row').length).toBeLessThanOrEqual(36)
  const scroll = host.querySelector<HTMLDivElement>('.ds-workspace-file-tree__scroll')!
  await act(async () => { scroll.scrollTop = 20199 * 28; scroll.dispatchEvent(new Event('scroll')) })
  const last = host.querySelector<HTMLButtonElement>('[data-tree-key="dir199/f99.py"]')!
  expect(last).toBeTruthy()
  await act(async () => last.click())
  expect(open).toHaveBeenCalledWith('dir199/f99.py')
  await click('workspaceTreeCollapseAll')
  expect(host.querySelectorAll('[draggable="true"]').length).toBe(0)
  list.mockClear()
  await click('workspaceTreeRefresh')
  expect(list.mock.calls.map(call => call[1])).toEqual([''])
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 270)) })
  expect(storage.mock.calls.length).toBeLessThan(5)
  expect(readExpandedDirs(workspace).size).toBe(0)
})

it('caps pending reads at four and never reopens after collapse', async () => {
  const pending: Array<() => void> = []
  let active = 0
  let peak = 0
  const list = vi.fn(async (_root: string, path: string) => {
    if (!path) return result(Array.from({ length: 20 }, (_, i) => dir(`d${i}`)))
    active += 1; peak = Math.max(peak, active)
    await new Promise<void>(resolve => pending.push(() => { active -= 1; resolve() }))
    return result([dir(`${path}/nested`)])
  })
  await mount(list)
  await click('workspaceTreeExpandAll')
  expect(pending.length).toBe(4)
  await click('workspaceTreeCollapseAll')
  await act(async () => pending.splice(0).forEach(resolve => resolve()))
  expect(peak).toBe(4)
  expect(list).toHaveBeenCalledTimes(5)
  expect(host.querySelector('[aria-expanded="true"]')).toBeNull()
  expect(host.querySelector('[aria-label="workspaceTreeExpandAll"]')).toBeTruthy()
})

it('marks hidden directories stale, reloads on opening and preserves original path case', async () => {
  let revision = 0
  const list = vi.fn(async (_root: string, path: string) => result(path ? [file(`Source/f${revision}.py`)] : [dir('Source')]))
  await mount(list)
  await click('workspaceTreeExpandAll')
  await click('workspaceTreeCollapseAll')
  revision = 1; list.mockClear()
  await click('workspaceTreeRefresh')
  expect(list.mock.calls.map(call => call[1])).toEqual([''])
  await act(async () => host.querySelector<HTMLButtonElement>('[data-tree-key="source"]')!.click())
  expect(list.mock.calls.map(call => call[1])).toEqual(['', 'Source'])
  expect(host.textContent).toContain('f1.py')
  expect(host.textContent).not.toContain('f0.py')
})

it('discards pending results across workspace switches', async () => {
  let release!: () => void
  const list = vi.fn(async (path: string) => {
    if (path === workspace) await new Promise<void>(resolve => { release = resolve })
    return result([file(path === workspace ? 'old.py' : 'new.py')])
  })
  await mount(list)
  await mount(list, vi.fn(), '/another-workspace')
  await act(async () => release())
  expect(host.textContent).toContain('new.py')
  expect(host.textContent).not.toContain('old.py')
})

it('coalesces overlapping refresh requests into a single follow-up', async () => {
  const pending: Array<() => void> = []
  let delay = false
  const list = vi.fn(async () => {
    if (delay) await new Promise<void>(resolve => pending.push(resolve))
    return result([file('demo.py')])
  })
  await mount(list)
  delay = true; list.mockClear()
  await click('workspaceTreeRefresh')
  await click('workspaceTreeRefresh')
  await click('workspaceTreeRefresh')
  expect(list).toHaveBeenCalledTimes(1)
  await act(async () => pending.shift()!())
  expect(list).toHaveBeenCalledTimes(2)
  await act(async () => pending.shift()!())
  expect(pending.length).toBe(0)
})

it('restores only reachable expanded directories and respects auxiliary filtering', async () => {
  writeExpandedDirs(workspace, new Set(['Source', 'Source/Child', 'hidden/child', 'node_modules']))
  const list = vi.fn(async (_root: string, path: string) => result(path === ''
    ? [dir('Source'), dir('hidden'), dir('node_modules')]
    : path === 'Source' ? [dir('Source/Child')] : [file(`${path}/demo.py`)]))
  await mount(list)
  expect(list.mock.calls.map(call => call[1])).toEqual(['', 'Source', 'Source/Child'])
  expect(host.textContent).toContain('demo.py')
  await click('workspaceTreeShowAll')
  expect(list.mock.calls.map(call => call[1])).toContain('node_modules')
})

it('moves keyboard focus beyond the rendered window', async () => {
  await mount(vi.fn(async () => result(Array.from({ length: 1000 }, (_, i) => file(`f${i}.py`)))))
  const first = host.querySelector<HTMLButtonElement>('[data-tree-key="f0.py"]')!
  await act(async () => { first.focus(); first.dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true })) })
  expect((document.activeElement as HTMLElement).dataset.treeKey).toBe('f999.py')
  await act(async () => document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', bubbles: true })))
  expect((document.activeElement as HTMLElement).dataset.treeKey).toBe('f0.py')
})

it('keeps expand-all intent when a refresh arrives mid-scan', async () => {
  const pending: Array<() => void> = []
  let delay = true
  const list = vi.fn(async (_root: string, path: string) => {
    if (path === 'a' && delay) await new Promise<void>(resolve => pending.push(resolve))
    return result(path === '' ? [dir('a')] : path === 'a' ? [dir('a/nested')] : [file('a/nested/demo.py')])
  })
  await mount(list)
  await click('workspaceTreeExpandAll')
  await click('workspaceTreeRefresh')
  delay = false
  await act(async () => pending.splice(0).forEach(resolve => resolve()))
  expect(host.textContent).toContain('demo.py')
  expect(host.querySelectorAll('[aria-expanded="true"]').length).toBe(2)
})

it('shows read errors and retries on refresh', async () => {
  const list = vi.fn().mockResolvedValueOnce({ ok: false, message: 'Permission denied' })
    .mockResolvedValue(result([file('recovered.py')]))
  await mount(list)
  expect(host.textContent).toContain('Permission denied')
  await click('workspaceTreeRefresh')
  expect(host.textContent).toContain('recovered.py')
  expect(host.textContent).not.toContain('Permission denied')
})

it('flushes debounced expansion state on unmount', async () => {
  const list = vi.fn(async (_root: string, path: string) => result(path ? [file('a/demo.py')] : [dir('a')]))
  await mount(list)
  await click('workspaceTreeExpandAll')
  await act(async () => root.render(null))
  expect(readExpandedDirs(workspace).has('a')).toBe(true)
  await mount(list)
  expect(host.textContent).toContain('demo.py')
})

it('uses horizontal arrows to open, enter, leave and close a folder', async () => {
  await mount(vi.fn(async (_root: string, path: string) =>
    result(path ? [file('src/app.ts')] : [dir('src'), file('README.md')])))

  const folder = host.querySelector<HTMLButtonElement>('[data-tree-key="src"]')!
  folder.focus()
  const press = async (key: string) => {
    await act(async () => {
      document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
    })
  }
  await press('ArrowRight')
  expect(folder.getAttribute('aria-expanded')).toBe('true')
  await press('ArrowRight')
  expect((document.activeElement as HTMLElement).dataset.treeKey).toBe('src/app.ts')
  await press('ArrowLeft')
  expect(document.activeElement).toBe(folder)
  await press('ArrowLeft')
  expect(folder.getAttribute('aria-expanded')).toBe('false')
})
