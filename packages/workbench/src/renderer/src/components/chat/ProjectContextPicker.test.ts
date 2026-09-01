// @vitest-environment happy-dom

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProjectContextPicker } from './ProjectContextPicker'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const storeState = vi.hoisted(() => ({
  threads: [{ workspace: '/project', updatedAt: '2026-09-01T00:00:00Z' }],
  workspaceRoot: '/project',
  activateWorkspace: vi.fn(),
  chooseWorkspace: vi.fn(),
  createThread: vi.fn(),
  runtimeConnection: 'ready'
}))

vi.mock('react-i18next', async (importOriginal) => ({
  ...(await importOriginal<typeof import('react-i18next')>()),
  useTranslation: () => ({ t: (key: string) => key })
}))

vi.mock('../../store/chat-store', () => ({
  useChatStore: (selector: (state: typeof storeState) => unknown) => selector(storeState)
}))

describe('ProjectContextPicker menu placement', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    vi.stubGlobal('innerWidth', 800)
    vi.stubGlobal('innerHeight', 800)
    document.documentElement.style.setProperty('--ds-ui-scale', '0.8')
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 160,
      height: 32,
      top: 480,
      right: 320,
      bottom: 512,
      left: 160,
      x: 160,
      y: 480,
      toJSON: () => ({})
    })
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(async () => {
    await act(async () => root.unmount())
    container.remove()
    document.documentElement.style.removeProperty('--ds-ui-scale')
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('keeps an above portal clear of the trigger when the UI is scaled down', async () => {
    await act(async () => {
      root.render(
        createElement(ProjectContextPicker, {
          workspaceRoot: '/project',
          usePortal: true,
          menuPlacement: 'above'
        })
      )
    })

    await act(async () => {
      container.querySelector('button')?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    const menu = document.body.querySelector<HTMLElement>('.ds-project-context-menu')
    expect(menu?.style.left).toBe('200px')
    expect(menu?.style.bottom).toBe('408px')
    expect(menu?.style.maxHeight).toBe('580px')
  })
})
