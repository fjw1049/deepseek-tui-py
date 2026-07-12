/** Extensions that should open in the Preview tab as a rendered page. */
const HTML_PREVIEW_EXTENSIONS = new Set(['.html', '.htm', '.xhtml'])

export function isHtmlPreviewPath(path: string): boolean {
  const value = path.trim().toLowerCase()
  if (!value) return false
  const bare = value.split(/[?#]/, 1)[0] ?? value
  const slash = Math.max(bare.lastIndexOf('/'), bare.lastIndexOf('\\'))
  const base = slash >= 0 ? bare.slice(slash + 1) : bare
  const dot = base.lastIndexOf('.')
  if (dot < 0) return false
  return HTML_PREVIEW_EXTENSIONS.has(base.slice(dot))
}
