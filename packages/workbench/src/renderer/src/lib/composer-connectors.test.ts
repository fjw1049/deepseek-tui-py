import { describe, expect, it } from 'vitest'
import {
  buildComposerConnectorRows,
  diskServersFromMcpConfig,
  filterComposerConnectorRows,
  mediaConnectorTitle
} from './composer-connectors'

describe('composer-connectors', () => {
  it('shows yahoo from mcp.json under installed even if runtime omits it', () => {
    const diskServers = diskServersFromMcpConfig(
      JSON.stringify({
        mcpServers: {
          'yahoo-finance': {
            command: 'uvx',
            args: ['mcp-yahoo-finance'],
            enabled: true
          },
          'tikhub-wechat': {
            command: 'npx',
            args: ['mcp-remote', 'https://x'],
            enabled: true,
            load_policy: 'on_focus',
            catalog: 'media'
          }
        }
      })
    )

    const rows = buildComposerConnectorRows({
      diskServers,
      runtimeServers: [] // runtime cold / not listing yahoo yet
    })

    const installed = filterComposerConnectorRows(rows, 'installed', '')
    const media = filterComposerConnectorRows(rows, 'media', '')

    expect(installed.map((r) => r.id)).toContain('yahoo-finance')
    expect(installed.map((r) => r.id)).not.toContain('tikhub-wechat')
    expect(media.find((r) => r.id === 'tikhub-wechat')?.title).toBe('微信公众号')
    expect(media.find((r) => r.id === 'tikhub-wechat')?.needsConfig).toBe(false)
  })

  it('merges runtime connected dots onto disk installed servers', () => {
    const diskServers = diskServersFromMcpConfig(
      JSON.stringify({
        mcpServers: {
          'yahoo-finance': { command: 'uvx', args: ['mcp-yahoo-finance'], enabled: true }
        }
      })
    )
    const rows = buildComposerConnectorRows({
      diskServers,
      runtimeServers: [
        { name: 'yahoo-finance', enabled: true, connected: true, transport: 'stdio' }
      ]
    })
    expect(rows.find((r) => r.id === 'yahoo-finance')?.connected).toBe(true)
  })

  it('keeps media catalog titles when nothing configured', () => {
    const media = filterComposerConnectorRows(
      buildComposerConnectorRows({ diskServers: [], runtimeServers: [] }),
      'media',
      ''
    )
    expect(media.some((r) => r.title === '微信公众号')).toBe(true)
    expect(
      filterComposerConnectorRows(
        buildComposerConnectorRows({ diskServers: [], runtimeServers: [] }),
        'installed',
        ''
      )
    ).toEqual([])
  })

  it('resolves media titles', () => {
    expect(mediaConnectorTitle('tikhub-bilibili')).toBe('哔哩哔哩')
    expect(mediaConnectorTitle('yahoo-finance')).toBeNull()
  })
})
