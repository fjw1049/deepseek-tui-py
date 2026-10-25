// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { CuaPreview } from './CuaPreview'
import { useCuaPreviewStore } from '../../store/cua-preview-store'
const t = (key: string) => key
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }))
vi.mock('./use-cua-window-stream', () => ({ useCuaWindowStream: () => ({ status: 'permission', hasFrame: false, frameSize: null, appName: 'TextEdit', icon: null }) }))
vi.mock('./use-cua-still-frame', () => ({ useCuaStillFrame: () => ({ status: 'idle', frameSize: null }) }))
vi.mock('./CuaControlBar', () => ({ CuaControlBar: () => null }))
vi.mock('./CuaPermissionsDialog', () => ({ CuaPermissionsDialog: ({ onClose }: { onClose: () => void }) => createElement('button', { role: 'dialog', onClick: onClose }, 'permissions') }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root: ReturnType<typeof createRoot> | undefined
let host: HTMLDivElement | undefined
afterEach(async () => { await act(async () => root?.unmount()); host?.remove(); useCuaPreviewStore.setState({ sessions: {} }) })
it('keeps the permission dialog open across target changes and respects dismissal', async () => {
  let permission = 'denied'
  Object.defineProperty(window, 'dsGui', { configurable: true, value: {
    platform: 'darwin', getSettings: async () => ({ cuaWindowPreview: true }),
    getCuaScreenPermission: async () => ({ status: permission, appName: 'Electron', appId: 'preview-permission-test' }),
    runtimeRequest: async () => ({ ok: false })
  } })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  const session = { phase: 'live' as const, turnId: 'permission-test', appId: 'A', surface: 'app' as const, label: null, still: null, revision: 0 }
  useCuaPreviewStore.setState({ sessions: { test: session } })
  await act(async () => root!.render(createElement(CuaPreview, { threadId: 'test' })))
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  await act(async () => { (document.querySelector('[aria-expanded="false"]') as HTMLElement).click() })
  expect(document.querySelector('[role="dialog"]')).not.toBeNull()
  await act(async () => { useCuaPreviewStore.setState({ sessions: { test: { ...session, appId: 'B' } } }) })
  expect(document.querySelector('[role="dialog"]')).not.toBeNull()
  await act(async () => { (document.querySelector('[role="dialog"]') as HTMLElement).click() })
  await act(async () => { useCuaPreviewStore.setState({ sessions: { test: { ...session, appId: 'C' } } }) })
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  await act(async () => { useCuaPreviewStore.setState({ sessions: { test: { ...session, turnId: 'next-turn' } } }) })
  expect(document.querySelector('[role="dialog"]')).toBeNull()
  await act(async () => { (document.querySelector('[aria-expanded="false"]') as HTMLElement).click() })
  const refreshed = vi.fn()
  window.addEventListener('cua-permission-recheck', refreshed)
  try {
    permission = 'granted'
    await act(async () => window.dispatchEvent(new Event('focus')))
    expect(refreshed).toHaveBeenCalled()
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    permission = 'denied'
    await act(async () => window.dispatchEvent(new Event('focus')))
    expect(document.querySelector('[role="dialog"]')).not.toBeNull()
  } finally { window.removeEventListener('cua-permission-recheck', refreshed) }
})


it('does not request screen recording for browser screenshots', async () => {
  const permission = vi.fn(async () => ({ status: 'denied', appName: 'Electron', appId: 'browser-test' }))
  Object.defineProperty(window, 'dsGui', { configurable: true, value: {
    platform: 'darwin', getSettings: async () => ({ cuaWindowPreview: true }),
    getCuaScreenPermission: permission, runtimeRequest: async () => ({ ok: false })
  } })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  useCuaPreviewStore.setState({ sessions: { browser: {
    phase: 'live', turnId: 'browser-turn', appId: null, surface: 'browser', label: null, still: null, revision: 0
  } } })
  await act(async () => root!.render(createElement(CuaPreview, { threadId: 'browser' })))
  await act(async () => { (document.querySelector('[aria-expanded="false"]') as HTMLElement).click() })
  expect(permission).not.toHaveBeenCalled()
  expect(document.querySelector('[role="dialog"]')).toBeNull()
})
