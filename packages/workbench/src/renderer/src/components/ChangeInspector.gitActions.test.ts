// @vitest-environment happy-dom
// Pins the Changes-toolbar chip state machine: which action the primary button offers for a
// given staged/ahead/behind/upstream combination. "Create PR" must never come back onto the
// chip (it lives in the dropdown), and an in-sync branch must show a greyed push, not a PR.
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { GitBranchesResult } from '@shared/git-branches'
import type { GitWorkingChangesResult } from '@shared/git-working-changes'
import { useChatStore } from '../store/chat-store'
import { ChangeInspector } from './ChangeInspector'

const state = vi.hoisted(() => ({
  branches: null as unknown,
  changes: null as unknown,
  remote: null as unknown
}))

vi.mock('./chat/FileChip', () => ({ FileChip: () => null, FileTypeIcon: () => null }))
vi.mock('react-i18next', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-i18next')>()),
  useTranslation: () => ({ t: (key: string) => key })
}))
vi.mock('../hooks/use-git-working-changes', () => ({
  useGitWorkingChanges: () => ({ result: state.changes, loading: false, reload: vi.fn() }),
  useGitBranchCompareBase: () => ['main', vi.fn()]
}))
vi.mock('../hooks/use-git-branches', () => ({
  useGitBranches: () => ({ result: state.branches, loading: false, reload: vi.fn() })
}))
vi.mock('../hooks/use-github-repository', () => ({
  useGitHubRepository: () => ({ result: state.remote })
}))
vi.mock('../hooks/use-workspace-dirty-git-refresh', () => ({ useWorkspaceDirtyGitRefresh: () => {} }))

type BranchState = Extract<GitBranchesResult, { ok: true }>
type ChangesState = Extract<GitWorkingChangesResult, { ok: true }>

const branches = (over: Partial<BranchState>): BranchState => ({
  ok: true,
  repositoryRoot: '/repo',
  currentBranch: 'feature/x',
  detached: false,
  inferredBranch: null,
  branches: [],
  defaultBranch: 'main',
  recommendedBase: 'main',
  dirtyCount: 0,
  upstream: 'origin/feature/x',
  ahead: 0,
  behind: 0,
  hasRemote: true,
  remoteRefreshError: null,
  ...over
})

const changes = (staged: number): ChangesState => {
  const file = (path: string, stage: 'staged' | 'unstaged') =>
    ({ path, status: 'modified' as const, stage, patch: '' })
  return {
    ok: true,
    repositoryRoot: '/repo',
    scope: 'working-tree',
    files: [],
    stagedFiles: Array.from({ length: staged }, (_, i) => file(`s${i}.ts`, 'staged')),
    unstagedFiles: []
  }
}

let container: HTMLDivElement
let root: Root
const initial = useChatStore.getState()
const chip = (): HTMLButtonElement => container.querySelector('.ds-change-git-actions__primary')!
const menuButton = (): HTMLButtonElement =>
  container.querySelector('button[aria-label="gitActionsMenu"]')!

const mount = async (branchState: Partial<BranchState>, staged: number): Promise<void> => {
  state.branches = branches(branchState)
  state.changes = changes(staged)
  await act(async () =>
    root.render(createElement(ChangeInspector, { onContextChange: () => {} }))
  )
}

beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  state.remote = {
    ok: true,
    nameWithOwner: 'acme/repo',
    url: 'https://github.com/acme/repo',
    host: 'github.com',
    provider: 'github'
  }
  useChatStore.setState({ workspaceRoot: '/repo', activeThreadId: null, inspectorSelectedId: null })
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  useChatStore.setState(initial, true)
})

it('commits when something is staged', async () => {
  await mount({}, 2)
  expect(chip().getAttribute('aria-label')).toBe('gitCommitStagedCount')
  expect(chip().disabled).toBe(false)
})

it('offers a greyed push — not a PR — when the branch is in sync', async () => {
  await mount({}, 0)
  expect(chip().getAttribute('aria-label')).toBe('gitPushUpToDate')
  expect(chip().title).toBe('gitPushUpToDate')
  expect(chip().disabled).toBe(true)
})

it('keeps create-PR in the dropdown while the chip pushes', async () => {
  await mount({ ahead: 2 }, 0)
  expect(chip().getAttribute('aria-label')).toBe('gitPushCommits')
  expect(chip().disabled).toBe(false)
  act(() => menuButton().click())
  const item = Array.from(container.querySelectorAll('[role="menuitem"]')).find((el) =>
    el.textContent?.includes('gitCreatePullRequest')
  )
  expect(item).toBeDefined()
})

it('pulls when behind and syncs when diverged', async () => {
  await mount({ behind: 3 }, 0)
  expect(chip().getAttribute('aria-label')).toBe('gitPullCommits')
  await mount({ ahead: 2, behind: 3 }, 0)
  expect(chip().getAttribute('aria-label')).toBe('gitSyncChanges')
})

it('publishes a branch with no upstream, then falls back to the menu', async () => {
  await mount({ upstream: null }, 0)
  expect(chip().getAttribute('aria-label')).toBe('gitPublishBranch')
  expect(chip().disabled).toBe(false)
  await mount({ upstream: null, hasRemote: false }, 0)
  expect(chip().getAttribute('aria-label')).toBe('gitActionsMenu')
})
