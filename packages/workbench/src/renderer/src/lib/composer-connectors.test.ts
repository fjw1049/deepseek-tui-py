import { describe, expect, it } from 'vitest'
import {
  classifyConnector,
  ensurePresetConnectors,
  withDefaultOnFocusPolicy
} from './connector-groups'
import {
  buildComposerConnectorRows,
  composerConnectorDotTone,
  diskServersFromMcpConfig,
  filterComposerConnectorRows,
  isComposerConnectorSelectable,
  mediaConnectorTitle,
  parseMcpRuntimeServers,
  resolveConnectorRuntimeStatus
} from './composer-connectors'

describe('connector-groups', () => {
  it('classifies bing as default and yahoo as activated', () => {
    expect(classifyConnector('bing-search')).toBe('default')
    expect(classifyConnector('bing-cn-mcp-server')).toBe('default')
    expect(classifyConnector('yahoo-finance')).toBe('activated')
    expect(classifyConnector('tikhub-zhihu')).toBe('activated')
    expect(classifyConnector('some-market-mcp')).toBe('activated')
  })

  it('puts explicit progressive servers under default', () => {
    expect(classifyConnector('custom-search', 'progressive')).toBe('default')
    expect(classifyConnector('custom-search', 'on_focus')).toBe('activated')
  })

  it('defaults missing load_policy to on_focus', () => {
    expect(withDefaultOnFocusPolicy({ command: 'npx', args: ['x'] }).load_policy).toBe(
      'on_focus'
    )
    expect(
      withDefaultOnFocusPolicy({ command: 'npx', load_policy: 'progressive' }).load_policy
    ).toBe('progressive')
  })

  it('seeds bing + yahoo on empty mcp.json', () => {
    const { next, changed } = ensurePresetConnectors('{\n  "mcpServers": {}\n}\n')
    expect(changed).toBe(true)
    const servers = diskServersFromMcpConfig(next)
    expect(servers.find((s) => s.id === 'bing-search')?.loadPolicy).toBe('progressive')
    expect(servers.find((s) => s.id === 'yahoo-finance')?.loadPolicy).toBe('on_focus')
  })

  it('migrates existing bing alias and yahoo policies without duplicating bing', () => {
    const raw = JSON.stringify({
      mcpServers: {
        'bing-cn-mcp-server': {
          command: 'npx',
          args: ['bing-cn-mcp'],
          load_policy: 'on_focus'
        },
        'yahoo-finance': {
          command: 'uvx',
          args: ['mcp-yahoo-finance'],
          enabled: true
        }
      }
    })
    const { next, changed } = ensurePresetConnectors(raw)
    expect(changed).toBe(true)
    const servers = diskServersFromMcpConfig(next)
    expect(servers.map((s) => s.id)).toEqual(['bing-cn-mcp-server', 'yahoo-finance'])
    expect(servers.find((s) => s.id === 'bing-cn-mcp-server')?.loadPolicy).toBe('progressive')
    expect(servers.find((s) => s.id === 'yahoo-finance')?.loadPolicy).toBe('on_focus')
    expect(servers.find((s) => s.id === 'bing-cn-mcp-server')?.summary).toContain('-y')
  })
})

describe('composer-connectors', () => {
  it('puts bing under default and yahoo / tikhub under activated', () => {
    const diskServers = diskServersFromMcpConfig(
      JSON.stringify({
        mcp: {
          servers: {
            'bing-search': {
              command: 'npx',
              args: ['-y', 'bing-cn-mcp'],
              enabled: true,
              load_policy: 'progressive'
            },
            'yahoo-finance': {
              command: 'uvx',
              args: ['mcp-yahoo-finance'],
              enabled: true,
              load_policy: 'on_focus'
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

    const visible = filterComposerConnectorRows(rows, '')

    expect(visible.map((r) => r.id)).toEqual(['bing-search', 'tikhub-wechat', 'yahoo-finance'])
    expect(visible[0]?.title).toBe('Bing Search')
    expect(visible[0]?.section).toBe('default')
    expect(visible.find((r) => r.id === 'tikhub-wechat')?.title).toBe('微信公众号')
    expect(visible.find((r) => r.id === 'tikhub-wechat')?.section).toBe('activated')
    expect(visible.find((r) => r.id === 'yahoo-finance')?.title).toBe('Yahoo Finance')
    expect(visible.find((r) => r.id === 'yahoo-finance')?.section).toBe('activated')
    expect(filterComposerConnectorRows(rows, 'yahoo').map((r) => r.id)).toEqual(['yahoo-finance'])
  })

  it('merges runtime connected dots onto disk default servers', () => {
    const diskServers = diskServersFromMcpConfig(
      JSON.stringify({
        mcpServers: {
          'bing-search': {
            command: 'npx',
            args: ['-y', 'bing-cn-mcp'],
            enabled: true,
            load_policy: 'progressive'
          }
        }
      })
    )
    const rows = buildComposerConnectorRows({
      diskServers,
      runtimeServers: [
        { name: 'bing-search', enabled: true, connected: true, transport: 'stdio' }
      ]
    })
    expect(rows.find((r) => r.id === 'bing-search')?.connected).toBe(true)
    expect(rows.find((r) => r.id === 'bing-search')?.status).toBe('connected')
    expect(rows.find((r) => r.id === 'bing-search')?.section).toBe('default')
  })

  it('maps runtime status onto dots and blocks failed rows', () => {
    expect(resolveConnectorRuntimeStatus({ status: 'connected' })).toBe('connected')
    expect(resolveConnectorRuntimeStatus({ status: 'connecting' })).toBe('connecting')
    expect(resolveConnectorRuntimeStatus({ status: 'failed' })).toBe('failed')
    expect(resolveConnectorRuntimeStatus({ enabled: false })).toBe('disabled')
    expect(resolveConnectorRuntimeStatus({ connected: true })).toBe('connected')
    expect(resolveConnectorRuntimeStatus(undefined)).toBe('connecting')
    expect(composerConnectorDotTone({ status: 'connected' })).toBe('green')
    expect(composerConnectorDotTone({ status: 'connecting' })).toBe('yellow')
    expect(composerConnectorDotTone({ status: 'failed' })).toBe('red')
    expect(
      isComposerConnectorSelectable({ enabled: true, status: 'connected' })
    ).toBe(true)
    expect(
      isComposerConnectorSelectable({ enabled: true, status: 'connecting' })
    ).toBe(false)
    expect(isComposerConnectorSelectable({ enabled: true, status: 'failed' })).toBe(false)
    expect(isComposerConnectorSelectable({ enabled: true, status: 'disabled' })).toBe(false)
    expect(parseMcpRuntimeServers('{"servers":[{"name":"bing","status":"connected"}]}')).toEqual([
      { name: 'bing', status: 'connected' }
    ])
    expect(parseMcpRuntimeServers('not-json')).toEqual([])
  })

  it('does not treat a disconnected on_focus server as failed', () => {
    const diskServers = diskServersFromMcpConfig(
      JSON.stringify({
        mcpServers: {
          'yahoo-finance': {
            command: 'uvx',
            args: ['mcp-yahoo-finance'],
            enabled: true,
            load_policy: 'on_focus'
          }
        }
      })
    )
    const rows = buildComposerConnectorRows({
      diskServers,
      runtimeServers: [
        {
          name: 'yahoo-finance',
          enabled: true,
          connected: false,
          status: 'connecting',
          load_policy: 'on_focus'
        }
      ]
    })
    const yahoo = rows.find((r) => r.id === 'yahoo-finance')
    expect(yahoo?.status).toBe('connecting')
    expect(yahoo?.connected).toBe(false)
    expect(isComposerConnectorSelectable(yahoo!)).toBe(false)
    expect(composerConnectorDotTone(yahoo!)).toBe('yellow')
  })

  it('greys out a failed connector even when it is enabled on disk', () => {
    const diskServers = diskServersFromMcpConfig(
      JSON.stringify({
        mcpServers: {
          'yahoo-finance': {
            command: 'uvx',
            args: ['mcp-yahoo-finance'],
            enabled: true,
            load_policy: 'on_focus'
          }
        }
      })
    )
    const rows = buildComposerConnectorRows({
      diskServers,
      runtimeServers: [
        {
          name: 'yahoo-finance',
          enabled: true,
          connected: false,
          status: 'failed',
          error: "Failed to load connector 'yahoo-finance'",
          load_policy: 'on_focus'
        }
      ]
    })
    const yahoo = rows.find((r) => r.id === 'yahoo-finance')
    expect(yahoo?.status).toBe('failed')
    expect(isComposerConnectorSelectable(yahoo!)).toBe(false)
    expect(composerConnectorDotTone(yahoo!)).toBe('red')
  })

  it('does not list unconfigured media catalog stubs', () => {
    const rows = buildComposerConnectorRows({ diskServers: [], runtimeServers: [] })
    expect(rows).toEqual([])
    expect(filterComposerConnectorRows(rows, '')).toEqual([])
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
