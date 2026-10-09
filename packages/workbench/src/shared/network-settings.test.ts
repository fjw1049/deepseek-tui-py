import { describe, expect, it } from 'vitest'
import { migrateNetworkSettings, normalizeNetworkSettings } from './network-settings'

describe('model network settings', () => {
  it('migrates only existing Devpilot users, and an explicit empty list stays empty', () => {
    expect(migrateNetworkSettings(['http://devpilot.zhonganonline.com/api']).bypassHosts)
      .toEqual(['devpilot.zhonganonline.com'])
    expect(migrateNetworkSettings(['https://example.org']).bypassHosts).toEqual([])
    expect(normalizeNetworkSettings({ mode: 'system', bypassHosts: [] }).bypassHosts).toEqual([])
  })
  it('normalizes exact hosts and removes duplicates', () => {
    expect(normalizeNetworkSettings({ mode: 'system', bypassHosts: [' EXAMPLE.COM ', 'example.com', '[::1]'] }))
      .toEqual({ mode: 'system', bypassHosts: ['example.com', '[::1]'] })
  })
  it.each(['https://example.com', '*.example.com', 'example.com:7890', 'example.com/path', 'user@example.com'])('rejects %s', (host) => {
    expect(() => normalizeNetworkSettings({ mode: 'system', bypassHosts: [host] })).toThrow()
  })
})
