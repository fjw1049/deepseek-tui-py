import type { McpServerEntry } from '../../lib/mcp-json-merge'

export type MediaCatalogItem = {
  id: string
  title: string
  description: string
  /** Path segment under https://mcp.tikhub.io/<segment>/mcp */
  tikhubPath: string
  brand: string
}

/**
 * Built-in media connectors (TikHub).
 * Written as nested ``mcp.servers`` entries matching TikHub's documented form:
 *
 * ```json
 * {
 *   "mcp": {
 *     "servers": {
 *       "tikhub-zhihu": {
 *         "command": "npx",
 *         "args": [
 *           "mcp-remote",
 *           "https://mcp.tikhub.io/zhihu/mcp",
 *           "--header",
 *           "Authorization: Bearer YOUR_API_KEY"
 *         ]
 *       }
 *     }
 *   }
 * }
 * ```
 *
 * Extra fields ``load_policy`` / ``catalog`` are app-local (on_focus media).
 */
export const MEDIA_CATALOG: MediaCatalogItem[] = [
  {
    id: 'tikhub-tiktok',
    title: 'TikTok',
    description: '采集 TikTok 视频、用户与评论公开数据。',
    tikhubPath: 'tiktok',
    brand: 'tiktok'
  },
  {
    id: 'tikhub-bilibili',
    title: '哔哩哔哩',
    description: '采集 B 站视频、评论与 UP 主公开数据。',
    tikhubPath: 'bilibili',
    brand: 'bilibili'
  },
  {
    id: 'tikhub-weibo',
    title: '微博',
    description: '采集微博动态、话题与用户公开数据。',
    tikhubPath: 'weibo',
    brand: 'weibo'
  },
  {
    id: 'tikhub-zhihu',
    title: '知乎',
    description: '采集知乎问答、文章与用户公开数据。',
    tikhubPath: 'zhihu',
    brand: 'zhihu'
  },
  {
    id: 'tikhub-reddit',
    title: 'Reddit',
    description: '采集 Reddit 帖子、评论与社区数据。',
    tikhubPath: 'reddit',
    brand: 'reddit'
  },
  {
    id: 'tikhub-wechat',
    title: '微信公众号',
    description: '采集微信公众号文章与账号公开数据。',
    tikhubPath: 'wechat',
    brand: 'wechat'
  },
  {
    id: 'tikhub-twitter',
    title: 'Twitter / X',
    description: '采集推文、用户与话题公开数据。',
    tikhubPath: 'twitter',
    brand: 'twitter'
  },
  {
    id: 'tikhub-threads',
    title: 'Threads',
    description: '采集 Threads 帖子与账号公开数据。',
    tikhubPath: 'threads',
    brand: 'threads'
  },
  {
    id: 'tikhub-xiaohongshu',
    title: '小红书',
    description: '采集小红书笔记与账号公开数据。',
    tikhubPath: 'xiaohongshu',
    brand: 'xiaohongshu'
  }
]

const API_KEY_PLACEHOLDER = 'YOUR_API_KEY'

export function buildTikhubServerEntry(item: MediaCatalogItem, apiKey: string): McpServerEntry {
  const key = apiKey.trim()
  return {
    command: 'npx',
    args: [
      'mcp-remote',
      `https://mcp.tikhub.io/${item.tikhubPath}/mcp`,
      '--header',
      `Authorization: Bearer ${key || API_KEY_PLACEHOLDER}`
    ],
    // App-local: media connectors load only under @mention.
    load_policy: 'on_focus',
    catalog: 'media'
  }
}

export function extractBearerFromEntry(entry: { args?: string[] } | null | undefined): string {
  const args = entry?.args ?? []
  for (let i = 0; i < args.length; i += 1) {
    if (args[i] === '--header' && typeof args[i + 1] === 'string') {
      const header = args[i + 1] ?? ''
      const match = /^Authorization:\s*Bearer\s+(.+)$/i.exec(header.trim())
      if (match?.[1] && match[1] !== API_KEY_PLACEHOLDER) {
        return match[1]
      }
    }
  }
  return ''
}
