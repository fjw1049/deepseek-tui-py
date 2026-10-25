import { afterEach, beforeEach, expect, it, vi } from 'vitest'
const provider = vi.hoisted(() => ({ interruptTurn: vi.fn() }))
vi.mock('../agent/registry', () => ({ getProvider: () => provider }))
import { useChatStore } from './chat-store'
import { noteCuaCallStarted, useCuaPreviewStore } from './cua-preview-store'

const initial = useChatStore.getState()
const start = { itemId: 'i', summary: 'cua_js', status: 'running', toolName: 'cua_js' } as const

beforeEach(() => {
  vi.resetAllMocks()
  vi.stubGlobal('window', { dsGui: { logError: vi.fn() } })
  useCuaPreviewStore.setState({ sessions: {}, floating: {} })
  useChatStore.setState({ ...initial, activeThreadId: 'a', currentTurnId: 'turn', busy: true }, true)
  noteCuaCallStarted('a', 'turn', start)
})
afterEach(() => { useChatStore.setState(initial, true); vi.unstubAllGlobals() })

it('Stop ends the preview even though no completion event arrives', async () => {
  provider.interruptTurn.mockResolvedValue(undefined)
  await useChatStore.getState().interrupt()
  expect(useChatStore.getState().currentTurnId).toBeNull()
  expect(useCuaPreviewStore.getState().sessions.a).toMatchObject({ phase: 'ended', outcome: 'stopped' })
})

it('switching threads leaves the running task preview alone', () => {
  useChatStore.setState({ activeThreadId: 'b', currentTurnId: null })
  expect(useCuaPreviewStore.getState().sessions.a?.phase).toBe('armed')
})
