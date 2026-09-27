/** Accept only our share route; a deep link never triggers a restore or sends a prompt. */
export function parseSharedConversationLink(raw: string): string | null {
  try {
    const deep = new URL(raw)
    if (deep.protocol !== 'deepseek-gui:' || deep.hostname !== 'share' || deep.username || deep.password || deep.hash) return null
    const value = deep.searchParams.get('url')
    if (!value || value.length > 4096) return null
    const link = new URL(value)
    const local = ['localhost', '127.0.0.1', '[::1]'].includes(link.hostname)
    if (link.protocol !== 'https:' && !(link.protocol === 'http:' && local)) return null
    if (link.username || link.password || link.search || link.hash || !/^\/s\/[A-Za-z0-9_-]{43}$/.test(link.pathname)) return null
    return link.href
  } catch { return null }
}
