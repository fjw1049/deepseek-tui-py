import type { PreviewElementPick } from './preview-element-picker'

/** Stable marker so timeline/title parsers can strip the wire envelope. */
export const PREVIEW_PICK_WIRE_MARKER = '[ds-preview-pick]'

/** Max modules held in Composer at once. */
export const PREVIEW_PICK_MAX = 5

const USER_REQUEST_MARKER = '用户要求：'
const EMPTY_REQUEST_FALLBACK = '(未填写具体要求，请根据选中模块做合理改进)'
const WIRE_INTRO =
  '请修改以下预览选中模块（先用 htmlSnippet 在文件里做唯一匹配；匹配不到再用 selector；不要整页重写）。'
const LEGACY_WIRE_INTRO_PREFIX = '请修改预览中选中的模块'

export type UpsertPreviewPickResult =
  | { kind: 'added'; picks: PreviewElementPick[] }
  | { kind: 'removed'; picks: PreviewElementPick[] }
  | { kind: 'limit'; picks: PreviewElementPick[] }

function pickKey(pick: PreviewElementPick): string {
  // Include htmlSnippet: class-less static elements collapse to identical
  // truncated tag/nth-of-type selectors, so selector alone would toggle off an
  // unrelated earlier pick. outerHTML disambiguates distinct nodes.
  return `${pick.filePath}\0${pick.selector}\0${pick.htmlSnippet}`
}

/**
 * Append a pick, toggle-remove if the same filePath+selector exists, or
 * signal limit when already at max distinct modules.
 */
export function upsertPreviewPick(
  current: readonly PreviewElementPick[],
  pick: PreviewElementPick,
  max: number = PREVIEW_PICK_MAX
): UpsertPreviewPickResult {
  const key = pickKey(pick)
  const existingIndex = current.findIndex((item) => pickKey(item) === key)
  if (existingIndex >= 0) {
    return {
      kind: 'removed',
      picks: current.filter((_, index) => index !== existingIndex)
    }
  }
  if (current.length >= max) {
    return { kind: 'limit', picks: [...current] }
  }
  return { kind: 'added', picks: [...current, pick] }
}

/** Short chip label shown in the composer / timeline (not the full context). */
export function formatPreviewPickChipLabel(pick: PreviewElementPick): string {
  const file = pick.filePath.split(/[\\/]/).filter(Boolean).at(-1) || pick.filePath || 'html'
  const target = (pick.selector || pick.tagName || 'element').trim()
  const label = `${file} · ${target}`
  return label.length > 42 ? `${label.slice(0, 41)}…` : label
}

function pickToJsonObject(pick: PreviewElementPick): Record<string, unknown> {
  return {
    filePath: pick.filePath,
    selector: pick.selector,
    tagName: pick.tagName,
    ...(pick.id ? { id: pick.id } : {}),
    classes: pick.classes,
    textPreview: pick.textPreview,
    htmlSnippet: pick.htmlSnippet,
    ancestry: pick.ancestry
  }
}

/** Compact JSON payload for a single pick (tests / legacy helpers). */
export function formatPreviewPickJson(pick: PreviewElementPick): string {
  return JSON.stringify(pickToJsonObject(pick))
}

/** Compact JSON array embedded in the outbound wire message. */
export function formatPreviewPicksJson(picks: readonly PreviewElementPick[]): string {
  return JSON.stringify(picks.map(pickToJsonObject))
}

/**
 * Wire message for the agent: structured JSON context + the user's short request.
 * Composer / timeline UI only show chips + the request text.
 */
export function formatPreviewPickWireMessage(
  picks: PreviewElementPick | readonly PreviewElementPick[],
  userRequest: string
): string {
  const list = (Array.isArray(picks) ? picks : [picks]).filter(Boolean)
  const request = userRequest.trim()
  return [
    PREVIEW_PICK_WIRE_MARKER,
    WIRE_INTRO,
    '```json',
    formatPreviewPicksJson(list),
    '```',
    '',
    USER_REQUEST_MARKER,
    request || EMPTY_REQUEST_FALLBACK
  ].join('\n')
}

export type ParsedPreviewPickWire = {
  picks: PreviewElementPick[]
  /** User-visible request body (empty when only the fallback was sent). */
  userRequest: string
  chipLabels: string[]
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string')
    : []
}

function parsePickObject(data: Record<string, unknown>): PreviewElementPick | null {
  const filePath = typeof data.filePath === 'string' ? data.filePath.trim() : ''
  const selector = typeof data.selector === 'string' ? data.selector.trim() : ''
  const tagName = typeof data.tagName === 'string' ? data.tagName.trim() : ''
  if (!filePath || (!selector && !tagName)) return null
  return {
    filePath,
    selector: selector || tagName,
    tagName: tagName || 'div',
    ...(typeof data.id === 'string' && data.id.trim() ? { id: data.id.trim() } : {}),
    classes: asStringArray(data.classes).slice(0, 8),
    textPreview: typeof data.textPreview === 'string' ? data.textPreview : '',
    htmlSnippet: typeof data.htmlSnippet === 'string' ? data.htmlSnippet : '',
    ancestry: asStringArray(data.ancestry).slice(0, 3)
  }
}

/**
 * Parse a sent preview-pick wire message back into chips + short request for UI.
 * Supports JSON array (current), single object (legacy), and unmarked intro forms.
 */
export function parsePreviewPickWireMessage(text: string): ParsedPreviewPickWire | null {
  const trimmed = text.trim()
  if (!trimmed.includes('```json') || !trimmed.includes(USER_REQUEST_MARKER)) return null
  const hasMarker = trimmed.startsWith(PREVIEW_PICK_WIRE_MARKER)
  const hasIntro =
    trimmed.includes(WIRE_INTRO) || trimmed.includes(LEGACY_WIRE_INTRO_PREFIX)
  if (!hasMarker && !hasIntro) return null

  const jsonMatch = /```json\s*\n([\s\S]*?)\n```/.exec(trimmed)
  if (!jsonMatch?.[1]) return null

  try {
    const data = JSON.parse(jsonMatch[1]) as unknown
    const rawList: Record<string, unknown>[] = Array.isArray(data)
      ? data.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
      : data && typeof data === 'object'
        ? [data as Record<string, unknown>]
        : []
    const picks = rawList
      .map((item) => parsePickObject(item))
      .filter((item): item is PreviewElementPick => item != null)
    if (picks.length === 0) return null

    const reqIdx = trimmed.lastIndexOf(USER_REQUEST_MARKER)
    const rawRequest = trimmed.slice(reqIdx + USER_REQUEST_MARKER.length).replace(/^\n/, '').trim()
    const userRequest = rawRequest === EMPTY_REQUEST_FALLBACK ? '' : rawRequest

    return {
      picks,
      userRequest,
      chipLabels: picks.map((pick) => formatPreviewPickChipLabel(pick))
    }
  } catch {
    return null
  }
}
