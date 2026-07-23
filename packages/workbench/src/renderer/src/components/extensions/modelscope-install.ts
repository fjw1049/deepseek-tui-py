/**
 * Client-side extraction of an installable MCP entry from a ModelScope listing.
 * The public catalog does not expose a structured install config — it is buried
 * in the item's README markdown (fenced ```json / ~~~json with an `mcpServers`
 * object) — or, rarely, in a remote `deployedUrl`.
 */
import { withDefaultOnFocusPolicy } from '../../lib/connector-groups'
import { parseMcpConfigDocument, type McpServerEntry } from '../../lib/mcp-json-merge'
import type { MarketplaceItem } from '../../../../shared/ds-gui-api'

function serversFromDoc(doc: Record<string, unknown>): Record<string, McpServerEntry> | undefined {
  const mcp = doc.mcp
  if (mcp && typeof mcp === 'object' && !Array.isArray(mcp)) {
    const nested = (mcp as Record<string, unknown>).servers
    if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
      return nested as Record<string, McpServerEntry>
    }
  }
  const servers = doc.mcpServers ?? doc.servers
  if (servers && typeof servers === 'object' && !Array.isArray(servers)) {
    return servers as Record<string, McpServerEntry>
  }
  return undefined
}

/** First JSON object in the README that contains an `mcpServers`/`servers` table. */
function extractMcpConfigBlock(readme: string): Record<string, unknown> | null {
  // Grab fenced code blocks (``` or ~~~), preferring ones that mention mcpServers.
  const fencePattern = /(?:```|~~~)[a-zA-Z]*\s*([\s\S]*?)(?:```|~~~)/g
  const candidates: string[] = []
  for (const match of readme.matchAll(fencePattern)) {
    const body = (match[1] ?? '').trim()
    if (
      body.includes('mcpServers') ||
      body.includes('"servers"') ||
      body.includes('"mcp"')
    ) {
      candidates.push(body)
    }
  }
  for (const body of candidates) {
    try {
      const doc = parseMcpConfigDocument(body)
      if (serversFromDoc(doc)) return doc
    } catch {
      /* try next candidate */
    }
  }
  return null
}

export type McpInstallResolution =
  | { mode: 'auto'; entry: McpServerEntry }
  | { mode: 'manual'; reason: 'no-config' }

/**
 * Resolve how to install an MCP item:
 * - a remote `deployedUrl` → a `{ url }` entry
 * - else an `mcpServers` block parsed from the README → its first server entry
 * - else `manual` (caller should send the user to the source page).
 */
export function resolveMcpInstall(item: MarketplaceItem): McpInstallResolution {
  if (item.deployedUrl) {
    return {
      mode: 'auto',
      entry: withDefaultOnFocusPolicy({ url: item.deployedUrl })
    }
  }
  const doc = extractMcpConfigBlock(item.readme)
  if (doc) {
    const servers = serversFromDoc(doc)
    const entry = servers?.[item.id] ?? (Object.values(servers ?? {})[0] as McpServerEntry | undefined)
    if (entry && (entry.command || entry.url)) {
      return { mode: 'auto', entry: withDefaultOnFocusPolicy(entry) }
    }
  }
  return { mode: 'manual', reason: 'no-config' }
}
