/** Extensions that should open as a rendered image in the workspace editor. */
const IMAGE_PREVIEW_EXTENSIONS = new Set([
  '.png',
  '.jpg',
  '.jpeg',
  '.gif',
  '.webp',
  '.svg'
])

export function isImagePreviewPath(path: string): boolean {
  const value = path.trim().toLowerCase()
  if (!value) return false
  const bare = value.split(/[?#]/, 1)[0] ?? value
  const slash = Math.max(bare.lastIndexOf('/'), bare.lastIndexOf('\\'))
  const base = slash >= 0 ? bare.slice(slash + 1) : bare
  const dot = base.lastIndexOf('.')
  if (dot < 0) return false
  return IMAGE_PREVIEW_EXTENSIONS.has(base.slice(dot))
}
