import { describe, expect, it } from 'vitest'
import {
  buildTikhubServerEntry,
  extractBearerFromEntry,
  MEDIA_CATALOG
} from './media-catalog'
import { normalizeMcpLoadPolicy } from '../../lib/mcp-json-merge'

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

  it('extracts bearer tokens from args', () => {
    expect(
      extractBearerFromEntry({
        args: ['mcp-remote', 'https://x', '--header', 'Authorization: Bearer abc']
      })
    ).toBe('abc')
    expect(extractBearerFromEntry({ args: ['mcp-remote'] })).toBe('')
  })
})
