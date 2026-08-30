// @vitest-environment happy-dom

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { WorkspaceContextBar } from './WorkspaceContextBar'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

vi.mock('./ProjectContextPicker', async () => {
  const React = await import('react')
  return {
    ProjectContextPicker: () => React.createElement('button', null, 'project')
  }
})

vi.mock('./GitBranchPicker', async () => {
  const React = await import('react')
  return {
    GitBranchPicker: ({
      workspaceRoot,
      onCurrentBranchChange
    }: {
      workspaceRoot: string
      onCurrentBranchChange?: (branch: string | null) => void
    }) => {
      React.useEffect(() => {
        onCurrentBranchChange?.(workspaceRoot.includes('no-branch') ? null : 'main')
      }, [onCurrentBranchChange, workspaceRoot])
      return React.createElement('button', null, 'branch')
    }
  }
})

class FakeResizeObserver implements ResizeObserver {
  constructor(_callback: ResizeObserverCallback) {}
  disconnect(): void {}
  observe(): void {}
  unobserve(): void {}
}

describe('WorkspaceContextBar branch visibility', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    vi.stubGlobal('ResizeObserver', FakeResizeObserver)
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 400,
      height: 40,
      top: 0,
      right: 400,
      bottom: 40,
      left: 0,
      x: 0,
      y: 0,
      toJSON: () => ({})
    })
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(async () => {
    await act(async () => root.unmount())
    container.remove()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('hides the branch control and separator when no current branch exists', async () => {
    await act(async () => {
      root.render(createElement(WorkspaceContextBar, { workspaceRoot: '/workspace/no-branch' }))
    })

    expect(container.querySelector('.ds-workspace-context-sep')).toHaveProperty('hidden', true)
    expect(container.querySelector('.ds-workspace-context-branch')).toHaveProperty('hidden', true)
  })

  it('keeps the branch control and separator for a real branch', async () => {
    await act(async () => {
      root.render(createElement(WorkspaceContextBar, { workspaceRoot: '/workspace/with-branch' }))
    })

    expect(container.querySelector('.ds-workspace-context-sep')).toHaveProperty('hidden', false)
    expect(container.querySelector('.ds-workspace-context-branch')).toHaveProperty('hidden', false)
  })
})
