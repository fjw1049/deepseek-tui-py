import { describe, expect, it } from 'vitest'
import { classifyConnector, withDefaultOnFocusPolicy } from './connector-groups'
import {
  buildComposerConnectorRows,
  diskServersFromMcpConfig,
  filterComposerConnectorRows,
  mediaConnectorTitle
} from './composer-connectors'

describe('connector-groups', () => {
  it('classifies yahoo as builtin and others as activated', () => {
    expect(classifyConnector('yahoo-finance')).toBe('builtin')
    expect(classifyConnector('tikhub-zhihu')).toBe('activated')
    expect(classifyConnector('some-market-mcp')).toBe('activated')
  })

  it('defaults missing load_policy to on_focus', () => {
    expect(withDefaultOnFocusPolicy({ command: 'npx', args: ['x'] }).load_policy).toBe(
      'on_focus'
    )
    expect(
      withDefaultOnFocusPolicy({ command: 'npx', load_policy: 'progressive' }).load_policy
    ).toBe('progressive')
  })
})

describe('composer-connectors', () => {
  it('puts yahoo under builtin and tikhub under activated', () => {
    const diskServers = diskServersFromMcpConfig(
      JSON.stringify({
        mcp: {
          servers: {
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
        }
      })
    )

    const rows = buildComposerConnectorRows({
      diskServers,
      runtimeServers: []
    })

    const builtin = filterComposerConnectorRows(rows, 'builtin', '')
    const activated = filterComposerConnectorRows(rows, 'activated', '')

    expect(builtin.map((r) => r.id)).toEqual(['yahoo-finance'])
    expect(activated.map((r) => r.id)).toContain('tikhub-wechat')
    expect(activated.find((r) => r.id === 'tikhub-wechat')?.title).toBe('微信公众号')
  })

  it('merges runtime connected dots onto disk builtin servers', () => {
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
    expect(rows.find((r) => r.id === 'yahoo-finance')?.section).toBe('builtin')
  })

  it('does not list unconfigured media catalog stubs', () => {
    const rows = buildComposerConnectorRows({ diskServers: [], runtimeServers: [] })
    expect(rows).toEqual([])
    expect(filterComposerConnectorRows(rows, 'activated', '')).toEqual([])
    expect(filterComposerConnectorRows(rows, 'builtin', '')).toEqual([])
  })

  it('skips disabled disk servers', () => {
    const diskServers = diskServersFromMcpConfig(
      JSON.stringify({
        servers: {
          'tikhub-zhihu': {
            command: 'npx',
            args: ['mcp-remote', 'https://x'],
            enabled: false,
            load_policy: 'on_focus',
            catalog: 'media'
          }
        }
      })
    )
    const rows = buildComposerConnectorRows({ diskServers, runtimeServers: [] })
    expect(rows.map((r) => r.id)).not.toContain('tikhub-zhihu')
  })

  it('resolves media titles', () => {
    expect(mediaConnectorTitle('tikhub-bilibili')).toBe('哔哩哔哩')
    expect(mediaConnectorTitle('yahoo-finance')).toBeNull()
  })
})
