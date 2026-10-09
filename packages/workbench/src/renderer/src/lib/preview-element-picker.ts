/**
 * Bounded element context for HTML preview → Composer.
 */

export const PREVIEW_PICK_CONSOLE_PREFIX = '__DS_PREVIEW_PICK__v1__'

export const PREVIEW_PICK_TEXT_MAX = 200
export const PREVIEW_PICK_HTML_MAX = 1200
export const PREVIEW_PICK_ANCESTRY_MAX = 3

export type PreviewElementPickPayload = {
  selector: string
  tagName: string
  id?: string
  classes: string[]
  textPreview: string
  htmlSnippet: string
  ancestry: string[]
}

export type PreviewElementPick = PreviewElementPickPayload & {
  filePath: string
}

export type PreviewPickWireMessage =
  | { type: 'pick'; payload: PreviewElementPickPayload }
  | { type: 'cancel' }

export function parsePreviewPickConsoleMessage(message: string): PreviewPickWireMessage | null {
  if (message.length > 16_384) return null
  const trimmed = message.trim()
  if (!trimmed.startsWith(PREVIEW_PICK_CONSOLE_PREFIX)) return null
  const raw = trimmed.slice(PREVIEW_PICK_CONSOLE_PREFIX.length)
  try {
    const parsed = JSON.parse(raw) as PreviewPickWireMessage
    if (!parsed || typeof parsed !== 'object') return null
    if (parsed.type === 'cancel') return { type: 'cancel' }
    if (parsed.type !== 'pick' || !parsed.payload || typeof parsed.payload !== 'object') return null
    const payload = sanitizePickPayload(parsed.payload)
    return payload ? { type: 'pick', payload } : null
  } catch {
    return null
  }
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function sanitizePickPayload(raw: PreviewElementPickPayload): PreviewElementPickPayload | null {
  const selector = asString(raw.selector).trim()
  const tagName = asString(raw.tagName).trim().toLowerCase()
  if (!selector || !tagName) return null
  const classes = Array.isArray(raw.classes)
    ? raw.classes.filter((item): item is string => typeof item === 'string').slice(0, 8)
        .map((item) => item.slice(0, 128))
    : []
  const ancestry = Array.isArray(raw.ancestry)
    ? raw.ancestry.filter((item): item is string => typeof item === 'string').slice(0, PREVIEW_PICK_ANCESTRY_MAX)
        .map((item) => item.slice(0, 500))
    : []
  const id = asString(raw.id).trim() || undefined
  return {
    selector: selector.slice(0, 500),
    tagName: tagName.slice(0, 64),
    ...(id ? { id: id.slice(0, 128) } : {}),
    classes,
    textPreview: asString(raw.textPreview).slice(0, PREVIEW_PICK_TEXT_MAX),
    htmlSnippet: asString(raw.htmlSnippet).slice(0, PREVIEW_PICK_HTML_MAX),
    ancestry
  }
}
