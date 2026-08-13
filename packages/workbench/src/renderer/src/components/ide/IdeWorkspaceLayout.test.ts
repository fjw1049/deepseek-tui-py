import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { IdeWorkspaceLayout } from './IdeWorkspaceLayout'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: 'en' }
  })
}))

vi.mock('../../hooks/use-light-dismiss', () => ({
  useLightDismiss: () => undefined
}))

vi.mock('../../lib/workspace-label', () => ({
  workspaceLabelFromPath: (path: string) => path.split('/').filter(Boolean).pop() || path
}))

vi.mock('../../hooks/use-git-working-changes', () => ({
  useGitWorkingChanges: () => ({
    result: null,
    loading: false,
    reload: vi.fn(async () => undefined)
  })
}))

vi.mock('../../store/workspace-editor-store', () => ({
  useWorkspaceEditorStore: (
    selector: (state: {
      openFile: () => Promise<void>
      tabs: []
      activeTabId: null
    }) => unknown
  ) =>
    selector({
      openFile: vi.fn(async () => undefined),
      tabs: [],
      activeTabId: null
    })
}))

vi.mock('../workspace-editor/WorkspaceEditorPanel', () => ({
  WorkspaceEditorPanel: () => createElement('div', null, 'editor-panel')
}))

vi.mock('../ChangeInspector', () => ({
  ChangeInspector: () => createElement('div', null, 'change-inspector')
}))

describe('IdeWorkspaceLayout', () => {
  beforeEach(() => {
    const map = new Map<string, string>()
    const fakeStorage = {
      getItem: (key: string) => map.get(key) ?? null,
      setItem: (key: string, value: string) => {
        map.set(key, String(value))
      },
      removeItem: (key: string) => {
        map.delete(key)
      },
      clear: () => {
        map.clear()
      }
    }
    vi.stubGlobal('localStorage', fakeStorage)
    vi.stubGlobal('window', { localStorage: fakeStorage })
  })

  it('renders chat-mode exit control and activity bar labels', () => {
    const markup = renderToStaticMarkup(
      createElement(IdeWorkspaceLayout, {
        workspaceRoot: '/tmp/demo',
        blocks: [],
        projectLabel: 'demo',
        projectOptions: [{ path: '/tmp/demo', name: 'demo' }],
        onSelectProject: vi.fn(),
        chatRail: createElement('div', null, 'chat-rail'),
        onExitIdeMode: vi.fn(),
        onOpenFileInEditor: vi.fn()
      })
    )

    expect(markup).toContain('ideSwitchToChat')
    expect(markup).toContain('ideActivityFiles')
    expect(markup).toContain('ideActivityChanges')
    expect(markup).toContain('ideActivitySearch')
    expect(markup).toContain('chat-rail')
    expect(markup).toContain('demo')
    expect(markup).toContain('ideSwitchProject')
    expect(markup).toContain('/tmp/demo')
    expect(markup).toContain('ds-ide-project-picker__trigger')
    expect(markup).toContain('ds-ide-project-picker__name')
    expect(markup).toContain('ds-ide-activity-bar')
    expect(markup).toContain('bg-ds-canvas')
  })

  it('keeps the editor mounted when the Changes activity is selected', () => {
    window.localStorage.setItem('deepseekgui.layout.ideCenterTab', 'changes')
    const markup = renderToStaticMarkup(
      createElement(IdeWorkspaceLayout, {
        workspaceRoot: '/tmp/demo',
        blocks: [],
        projectLabel: 'demo',
        chatRail: createElement('div', null, 'chat-rail'),
        onExitIdeMode: vi.fn(),
        onOpenFileInEditor: vi.fn()
      })
    )
    expect(markup).toContain('editor-panel')
    expect(markup).toContain('ds-ide-changes-stage')
    expect(markup).toContain('ds-ide-changes-list')
  })
})
