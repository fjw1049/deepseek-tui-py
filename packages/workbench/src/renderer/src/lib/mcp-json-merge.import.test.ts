import { describe, expect, it } from 'vitest'
import {
  extractMcpServersFromDocument,
  parseMcpConfigDocument
} from './mcp-json-merge'

describe('extractMcpServersFromDocument', () => {
  it('accepts bare Cursor-style server maps', () => {
    const doc = parseMcpConfigDocument(
      JSON.stringify({
        'filo-mail-mcp': {
          type: 'streamablehttp',
          url: 'http://127.0.0.1:3129/mcp',
          headers: { Authorization: 'Bearer secret' }
        }
      })
    )
    const servers = extractMcpServersFromDocument(doc)
    expect(Object.keys(servers)).toEqual(['filo-mail-mcp'])
    expect(servers['filo-mail-mcp']?.url).toBe('http://127.0.0.1:3129/mcp')
    expect(servers['filo-mail-mcp']?.type).toBe('streamablehttp')
    expect(servers['filo-mail-mcp']?.headers?.Authorization).toBe('Bearer secret')
  })

  it('still prefers mcpServers wrapper', () => {
    const doc = parseMcpConfigDocument(
      JSON.stringify({
        mcpServers: {
          demo: { url: 'https://example.com/mcp' }
        }
      })
    )
    expect(extractMcpServersFromDocument(doc).demo?.url).toBe('https://example.com/mcp')
  })
})
