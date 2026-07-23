import { describe, expect, it } from 'vitest'
import {
  buildTikhubServerEntry,
  extractBearerFromEntry,
  MEDIA_CATALOG
} from './media-catalog'
import {
  mergeMcpServerIntoConfig,
  normalizeMcpLoadPolicy
} from '../../lib/mcp-json-merge'

describe('media-catalog', () => {
  it('builds on_focus tikhub entries with bearer header', () => {
    const item = MEDIA_CATALOG.find((entry) => entry.id === 'tikhub-wechat')
    expect(item).toBeTruthy()
    const entry = buildTikhubServerEntry(item!, 'secret-key')
    expect(entry.load_policy).toBe('on_focus')
    expect(entry.catalog).toBe('media')
    expect(entry.command).toBe('npx')
    expect(entry.args).toEqual([
      'mcp-remote',
      'https://mcp.tikhub.io/wechat/mcp',
      '--header',
      'Authorization: Bearer secret-key'
    ])
    expect(normalizeMcpLoadPolicy(entry.load_policy)).toBe('on_focus')
  })

  it('writes nested mcp.servers TikHub form', () => {
    const item = MEDIA_CATALOG.find((entry) => entry.id === 'tikhub-zhihu')
    expect(item).toBeTruthy()
    const entry = buildTikhubServerEntry(item!, 'YOUR_API_KEY')
    const next = mergeMcpServerIntoConfig('', 'tikhub-zhihu', entry)
    const doc = JSON.parse(next) as {
      mcp: { servers: Record<string, { command: string; args: string[] }> }
    }
    expect(doc.mcp.servers['tikhub-zhihu']).toEqual({
      command: 'npx',
      args: [
        'mcp-remote',
        'https://mcp.tikhub.io/zhihu/mcp',
        '--header',
        'Authorization: Bearer YOUR_API_KEY'
      ],
      load_policy: 'on_focus',
      catalog: 'media'
    })
  })

  it('includes tiktok in the catalog', () => {
    expect(MEDIA_CATALOG.some((item) => item.id === 'tikhub-tiktok')).toBe(true)
  })

  it('extracts bearer tokens from args', () => {
    expect(
      extractBearerFromEntry({
        args: ['mcp-remote', 'https://x', '--header', 'Authorization: Bearer abc']
      })
    ).toBe('abc')
    expect(extractBearerFromEntry({ args: ['mcp-remote'] })).toBe('')
  })
})
