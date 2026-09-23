// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'

const startup = vi.hoisted(() => {
  let ready!: () => void
  const pending = new Promise<void>((resolve) => { ready = resolve })
  return { pending, ready, boot: vi.fn(), setStartupPhase: vi.fn() }
})
vi.mock('./store/chat-store', () => ({ useChatStore: (select: (s: unknown) => unknown) => select({
  boot: startup.boot, setStartupPhase: startup.setStartupPhase,
  initialSetupOpen: false, runtimeConnection: 'ready'
}) }))
vi.mock('./i18n', () => ({ default: { t: (key: string) => key } }))
vi.mock('./components/chat/StreamdownAssistant', () => ({}))
vi.mock('./components/KineticGrid', () => ({ KineticGrid: () => null }))
vi.mock('./components/Workbench', async () => {
  await startup.pending
  return { Workbench: () => createElement('div', { 'data-testid': 'workbench' }, 'home') }
})
import AppShell from './AppShell'

it('keeps startup visible until the shell and its navigation modules are ready', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList)
  const container = document.createElement('div')
  const root = createRoot(container)
  try {
    await act(async () => root.render(createElement(AppShell)))
    expect(container.querySelector('.ds-startup-blank')).not.toBeNull()
    expect(container.textContent).not.toContain('startupRenderer')
    await act(async () => {
      startup.ready()
      await startup.pending
    })
    expect(container.querySelector('[data-testid="workbench"]')).not.toBeNull()
    expect(container.querySelector('.ds-startup-blank')).toBeNull()
  } finally {
    await act(async () => root.unmount())
    vi.restoreAllMocks()
  }
})
