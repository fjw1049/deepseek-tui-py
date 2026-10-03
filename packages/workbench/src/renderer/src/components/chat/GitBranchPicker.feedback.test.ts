// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { GitBranchPicker } from './GitBranchPicker'

const fixture = vi.hoisted(() => ({ t: (key: string) => key, result: { ok: false, reason: 'error', message: 'Git failed' } }))
vi.mock('../../hooks/use-git-branches', () => ({ useGitBranches: () => ({ result: fixture.result, loading: false, reload: vi.fn(), setResult: vi.fn() }) }))
vi.mock('../../hooks/use-workspace-dirty-git-refresh', () => ({ useWorkspaceDirtyGitRefresh: vi.fn() }))
vi.mock('../../store/chat-store', () => ({ useChatStore: (select: (s: { workspaceDirtyTick: number }) => unknown) => select({ workspaceDirtyTick: 0 }) }))
vi.mock('./GitLogDialog', () => ({ GitLogDialog: () => null }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: fixture.t }) }))
let host: HTMLDivElement
let root: Root
let viewport: HTMLDivElement
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement('div')
  viewport = document.createElement('div')
  viewport.id = 'global-feedback-viewport'
  document.body.append(host, viewport)
  root = createRoot(host)
})
afterEach(() => { act(() => root.unmount()); host.remove(); viewport.remove() })

it('stacks Git feedback with global feedback and dismisses only its own notice', async () => {
  const globalNotice = document.createElement('div')
  globalNotice.setAttribute('role', 'alert')
  globalNotice.textContent = 'Global failed'
  viewport.append(globalNotice)
  await act(async () => root.render(createElement(GitBranchPicker, { workspaceRoot: '/test' })))
  expect(viewport.querySelectorAll('[role="alert"]')).toHaveLength(2)
  const gitNotice = viewport.querySelectorAll('[role="alert"]')[1]
  expect(gitNotice.textContent).toContain('Git failed')
  expect(gitNotice.parentElement?.classList.contains('fixed')).toBe(false)
  act(() => viewport.querySelector<HTMLButtonElement>('[aria-label="close"]')!.click())
  expect(viewport.querySelectorAll('[role="alert"]')).toHaveLength(1)
  expect(viewport.textContent).toBe('Global failed')
})

it('falls back to a standalone top notice without the workbench viewport', async () => {
  viewport.remove()
  await act(async () => root.render(createElement(GitBranchPicker, { workspaceRoot: '/test' })))
  const notice = document.body.querySelector('[role="alert"]')!
  expect(notice.parentElement?.classList.contains('fixed')).toBe(true)
  expect(notice.parentElement?.classList.contains('top-14')).toBe(true)
  act(() => notice.querySelector<HTMLButtonElement>('[aria-label="close"]')!.click())
  expect(document.body.querySelector('[role="alert"]')).toBeNull()
})
