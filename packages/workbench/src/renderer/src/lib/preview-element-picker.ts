/**
 * Guest-page element picker for HTML preview → Composer.
 * The main process injects the shared picker scripts; picks return over console-message.
 */

import {
  PREVIEW_PICK_ANCESTRY_MAX, PREVIEW_PICK_CONSOLE_PREFIX, PREVIEW_PICK_HTML_MAX, PREVIEW_PICK_TEXT_MAX
} from '@shared/preview-picker-scripts'

export {
  PREVIEW_PICK_ANCESTRY_MAX, PREVIEW_PICK_CONSOLE_PREFIX, PREVIEW_PICK_HTML_MAX, PREVIEW_PICK_TEXT_MAX,
  buildPreviewPickerCleanupScript, buildPreviewPickerInjectScript
} from '@shared/preview-picker-scripts'
const PICK_MAP_ENTRIES_MAX = 16
const PICK_MAP_VALUE_MAX = 200

export type PreviewElementPickPayload = {
  selector: string
  tagName: string
  id?: string
  classes: string[]
  textPreview: string
  htmlSnippet: string
  ancestry: string[]
  /** Computed styles that usually explain how the element looks. */
  styles?: Record<string, string>
  /** Viewport box in CSS pixels. */
  rect?: { x: number; y: number; width: number; height: number }
  /** Identifying attributes (aria-label, href, data-testid, ...). */
  attributes?: Record<string, string>
  /** Parent's children in short form, the picked one prefixed with <!-- SELECTED -->. */
  siblingHtml?: string
}

/** Workspace HTML previews carry `filePath`; any other page carries `pageUrl` and an empty `filePath`. */
export type PreviewElementPick = PreviewElementPickPayload & {
  filePath: string
  pageUrl?: string
}

export type PreviewPickWireMessage =
  | { type: 'pick'; payload: PreviewElementPickPayload }
  | { type: 'cancel' }

export function parsePreviewPickConsoleMessage(message: string): PreviewPickWireMessage | null {
  if (message.length > 32_768) return null
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

/**
 * Electron <webview> console-message puts text on `event.message` (Electron 34+
 * also prefers event-object form over the old multi-arg listener). Be defensive
 * about shape so a silent undefined never kills the pick bridge.
 */
export function extractWebviewConsoleMessage(event: Event): string | null {
  const record = event as Event & {
    message?: unknown
    detail?: { message?: unknown } | unknown
  }
  if (typeof record.message === 'string' && record.message) return record.message
  if (
    record.detail &&
    typeof record.detail === 'object' &&
    typeof (record.detail as { message?: unknown }).message === 'string'
  ) {
    const nested = (record.detail as { message: string }).message
    return nested || null
  }
  return null
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
  const styles = sanitizeStringMap(raw.styles)
  const attributes = sanitizeStringMap(raw.attributes)
  const rect = sanitizeRect(raw.rect)
  const siblingHtml = asString(raw.siblingHtml).slice(0, PREVIEW_PICK_HTML_MAX)
  return {
    selector: selector.slice(0, 500),
    tagName: tagName.slice(0, 64),
    ...(id ? { id: id.slice(0, 128) } : {}),
    classes,
    textPreview: asString(raw.textPreview).slice(0, PREVIEW_PICK_TEXT_MAX),
    htmlSnippet: asString(raw.htmlSnippet).slice(0, PREVIEW_PICK_HTML_MAX),
    ancestry,
    ...(styles ? { styles } : {}),
    ...(rect ? { rect } : {}),
    ...(attributes ? { attributes } : {}),
    ...(siblingHtml ? { siblingHtml } : {})
  }
}

function sanitizeStringMap(value: unknown): Record<string, string> | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const entries = Object.entries(value as Record<string, unknown>)
    .filter((entry): entry is [string, string] => typeof entry[1] === 'string' && entry[1] !== '')
    .slice(0, PICK_MAP_ENTRIES_MAX)
    .map(([key, item]) => [key.slice(0, 64), item.slice(0, PICK_MAP_VALUE_MAX)])
  return entries.length ? Object.fromEntries(entries) : undefined
}

function sanitizeRect(value: unknown): PreviewElementPickPayload['rect'] {
  if (!value || typeof value !== 'object') return undefined
  const { x, y, width, height } = value as Record<string, unknown>
  const box = [x, y, width, height]
  if (!box.every((item) => typeof item === 'number' && Number.isFinite(item))) return undefined
  return { x: Math.round(x as number), y: Math.round(y as number), width: Math.round(width as number), height: Math.round(height as number) }
}
