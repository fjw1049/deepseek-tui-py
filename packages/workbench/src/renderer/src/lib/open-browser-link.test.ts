// @vitest-environment happy-dom
import { beforeEach, expect, it, vi } from 'vitest'
import { openBrowserLink } from './open-browser-link'
import { cacheSettingsSnapshot } from './settings-snapshot'
import type { AppSettingsV1 } from '@shared/app-settings'
const openExternal = vi.fn()
const preview = vi.fn()
vi.mock('./open-preview-url', () => ({ openPreviewUrl: (url: string) => preview(url) }))
beforeEach(() => {
  vi.clearAllMocks()
  Object.assign(window, { dsGui: { openExternal } })
  cacheSettingsSnapshot({ browserLinkTarget: 'external', browserLocalLinkTarget: 'internal' } as AppSettingsV1)
})
it('routes explicit local links separately from public websites', async () => {
  await openBrowserLink('http://localhost:5173/path')
  await openBrowserLink('http://127.0.0.2:8000')
  await openBrowserLink('http://[::1]:8000')
  expect(preview).toHaveBeenCalledTimes(3)
  await openBrowserLink('https://localhost.evil.test')
  expect(openExternal).toHaveBeenCalledWith('https://localhost.evil.test')
})
it('honors internal web links but keeps email external and unsafe schemes inert', async () => {
  cacheSettingsSnapshot({ browserLinkTarget: 'internal' } as AppSettingsV1)
  await openBrowserLink('https://example.com')
  await openBrowserLink('mailto:test@example.com')
  await openBrowserLink('javascript:alert(1)')
  await openBrowserLink('file:///etc/passwd')
  expect(preview).toHaveBeenCalledExactlyOnceWith('https://example.com')
  expect(openExternal).toHaveBeenCalledExactlyOnceWith('mailto:test@example.com')
})
