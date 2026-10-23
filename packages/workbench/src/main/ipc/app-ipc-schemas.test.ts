import { describe, expect, it } from 'vitest'
import {
  browserBridgeTabsPayloadSchema,
  isSafeOpenExternalUrl,
  runtimeRequestPayloadSchema,
  shellOpenExternalUrlSchema,
  sseStartPayloadSchema
} from './app-ipc-schemas'

describe('app-ipc-schemas', () => {
  it('normalizes runtime request paths', () => {
    const payload = runtimeRequestPayloadSchema.parse({
      path: 'v1/threads?limit=1',
      method: 'GET'
    })

    expect(payload.path).toBe('/v1/threads?limit=1')
  })

  it('allows only safe external URL protocols', () => {
    expect(isSafeOpenExternalUrl('https://deepseek.com')).toBe(true)
    expect(isSafeOpenExternalUrl('http://127.0.0.1:5173')).toBe(true)
    expect(isSafeOpenExternalUrl('mailto:zhongxingyuemail@gmail.com')).toBe(true)
    expect(isSafeOpenExternalUrl('javascript:alert(1)')).toBe(false)
    expect(isSafeOpenExternalUrl('file:///tmp/test')).toBe(false)
    expect(() => shellOpenExternalUrlSchema.parse('javascript:alert(1)')).toThrow(
      /Only http, https, and mailto URLs are allowed/
    )
  })

  it('rejects invalid SSE payloads', () => {
    expect(() =>
      sseStartPayloadSchema.parse({
        threadId: 'thread-1',
        sinceSeq: -1
      })
    ).toThrow()
  })
})


it('accepts the renderer input lock while rejecting invalid bridge tab fields', () => {
  const tab = { tabId: 'tab', webContentsId: 4, active: true, visible: true, inputBlocked: true }
  expect(browserBridgeTabsPayloadSchema.parse({ browserId: 'chat', tabs: [tab] }).tabs[0]).toEqual(tab)
  expect(() => browserBridgeTabsPayloadSchema.parse({ browserId: 'chat', tabs: [{ ...tab, inputBlocked: 'yes' }] })).toThrow()
  expect(() => browserBridgeTabsPayloadSchema.parse({ browserId: 'chat', tabs: [{ ...tab, unexpected: true }] })).toThrow()
})
