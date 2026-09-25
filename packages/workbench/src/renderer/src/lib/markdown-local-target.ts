/** Resolve a document-relative URL without confusing it with an app route. */
export function markdownLocalTarget(href: string, documentPath: string, workspaceRoot: string): { path: string; fragment: string } | null {
  if (!href || /^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(href)) return null
  try {
    const normalized = documentPath.replaceAll('\\', '/')
    const absolute = /^(?:\/|[a-z]:\/)/i.test(normalized)
      ? normalized
      : `${workspaceRoot.replaceAll('\\', '/').replace(/\/$/, '')}/${normalized}`
    const base = `file:///${absolute.replace(/^\//, '').split('/').map(encodeURIComponent).join('/')}`
    const resolved = new URL(href.replaceAll('\\', '/'), base)
    if (resolved.protocol !== 'file:') return null
    return {
      path: decodeURIComponent(resolved.pathname).replace(/^\/([a-z]:\/)/i, '$1'),
      fragment: decodeURIComponent(resolved.hash.slice(1))
    }
  } catch {
    return null
  }
}
