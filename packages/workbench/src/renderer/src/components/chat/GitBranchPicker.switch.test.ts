// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { GitBranchesResult } from '@shared/git-branches'
import { WorkspaceContextBar } from './WorkspaceContextBar'

const translate = vi.hoisted(() => (key: string) => key)
vi.mock('./ProjectContextPicker', () => ({ ProjectContextPicker: () => null }))
vi.mock('./EnvironmentPicker', () => ({ EnvironmentPicker: () => null }))
vi.mock('./GitLogDialog', () => ({ GitLogDialog: () => null }))
vi.mock('../../store/chat-store', () => ({
  useChatStore: (select: (state: { workspaceDirtyTick: number }) => unknown) =>
    select({ workspaceDirtyTick: 0 })
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: translate }) }))

const branchState: Extract<GitBranchesResult, { ok: true }> = {
  ok: true,
  repositoryRoot: '/repo',
  currentBranch: 'build_1001',
  detached: false,
  inferredBranch: null,
  branches: [
    { name: 'build_1001', current: true },
    { name: 'other', current: false }
  ],
  defaultBranch: 'build_1001',
  recommendedBase: 'build_1001',
  dirtyCount: 0,
  upstream: null,
  ahead: 0,
  behind: 0,
  hasRemote: false,
  remoteRefreshError: null
}
const read = vi.fn<() => Promise<GitBranchesResult>>()
const switchBranch = vi.fn<() => Promise<GitBranchesResult>>()
const stashAndSwitch = vi.fn<() => Promise<GitBranchesResult>>()
let host: HTMLDivElement
let root: Root
let previousGui: typeof window.dsGui

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  vi.stubGlobal('ResizeObserver', undefined)
  previousGui = window.dsGui
  read.mockReset().mockResolvedValue(branchState)
  switchBranch.mockReset()
  stashAndSwitch.mockReset()
  window.dsGui = {
    getGitBranches: read,
    switchGitBranch: switchBranch,
    stashAndSwitchGitBranch: stashAndSwitch
  } as unknown as typeof window.dsGui
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})

afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  window.dsGui = previousGui
  vi.unstubAllGlobals()
})

const trigger = (): HTMLButtonElement => host.querySelector('.ds-workspace-context-branch button')!
const menuBranch = (name: string): HTMLButtonElement =>
  Array.from(document.querySelectorAll<HTMLButtonElement>('.ds-git-branch-menu button'))
    .find((button) => button.textContent === name)!

async function openAndSwitch(): Promise<void> {
  await act(async () => root.render(createElement(WorkspaceContextBar, { workspaceRoot: '/repo' })))
  expect(host.querySelector('.ds-workspace-context-branch')).toHaveProperty('hidden', false)
  expect(trigger().getAttribute('aria-label')).toBe('build_1001')
  await act(async () => trigger().click())
  await act(async () => menuBranch('other').click())
  expect(switchBranch).toHaveBeenCalledWith('/repo', 'other')
}

it.each(['runtime_checkout', 'error'] as const)(
  'keeps the current branch and menu after switching fails with %s',
  async (reason) => {
    switchBranch.mockResolvedValue({ ok: false, reason, message: 'Switch failed' })
    await openAndSwitch()

    expect(document.querySelector('[role="alert"]')?.textContent).toContain(
      reason === 'runtime_checkout' ? 'gitRuntimeCheckoutSwitchBlocked' : 'Switch failed'
    )
    expect(read).toHaveBeenCalledTimes(2)
    expect(await read.mock.results[1]!.value).toEqual(branchState)
    expect(host.querySelector('.ds-workspace-context-branch')).toHaveProperty('hidden', false)
    expect(trigger().getAttribute('aria-label')).toBe('build_1001')
    expect(menuBranch('build_1001')).toBeDefined()
    expect(menuBranch('other')).toHaveProperty('disabled', false)
    expect(document.querySelector<HTMLButtonElement>('.ds-project-context-menu__footer button'))
      .toHaveProperty('disabled', false)
  }
)

const stashButton = (): HTMLButtonElement =>
  Array.from(document.querySelectorAll<HTMLButtonElement>('[role="alert"] button'))
    .find((button) => button.textContent === 'gitStashAndSwitch')!

it.each(['runtime_checkout', 'error'] as const)(
  'keeps the current branch after stashing and switching fails with %s',
  async (reason) => {
    switchBranch.mockResolvedValue({ ok: false, reason: 'dirty_worktree', message: 'Dirty' })
    stashAndSwitch.mockResolvedValue({ ok: false, reason, message: 'Stash switch failed' })
    await openAndSwitch()
    expect(host.querySelector('.ds-workspace-context-branch')).toHaveProperty('hidden', false)
    expect(trigger().getAttribute('aria-label')).toBe('build_1001')
    expect(document.querySelector('[role="alert"]')?.textContent).toContain('gitDirtySwitchBlocked')

    await act(async () => stashButton().click())
    expect(stashAndSwitch).toHaveBeenCalledWith('/repo', 'other')
    expect(document.querySelector('[role="alert"]')?.textContent).toContain(
      reason === 'runtime_checkout' ? 'gitRuntimeCheckoutSwitchBlocked' : 'Stash switch failed'
    )
    expect(host.querySelector('.ds-workspace-context-branch')).toHaveProperty('hidden', false)
    expect(trigger().getAttribute('aria-label')).toBe('build_1001')
    await act(async () => trigger().click())
    expect(menuBranch('build_1001')).toBeDefined()
    expect(menuBranch('other')).toHaveProperty('disabled', false)
  }
)

it.each([false, true])('updates the current branch after a successful switch (stash: %s)', async (stash) => {
  const switched: GitBranchesResult = {
    ...branchState,
    currentBranch: 'other',
    branches: branchState.branches.map((branch) => ({ ...branch, current: branch.name === 'other' }))
  }
  switchBranch.mockResolvedValue(stash
    ? { ok: false, reason: 'dirty_worktree', message: 'Dirty' }
    : switched)
  stashAndSwitch.mockResolvedValue(switched)
  await openAndSwitch()
  if (stash) await act(async () => stashButton().click())

  expect(host.querySelector('.ds-workspace-context-branch')).toHaveProperty('hidden', false)
  expect(trigger().getAttribute('aria-label')).toBe('other')
  expect(trigger().getAttribute('aria-expanded')).toBe('false')
  expect(document.querySelector('.ds-git-branch-menu')).toBeNull()
  expect(document.querySelector('[role="alert"]')).toBeNull()
})
