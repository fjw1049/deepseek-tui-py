/**
 * Parse wire-format focus prefixes that the composer prepends on send:
 *   `@plugin:<name> …`  — session plugin mount
 *   `/<skill> …`        — per-turn skill focus
 *   `@<connector> …`    — per-turn MCP connector focus
 *
 * Used by the timeline to render an icon+name chip instead of raw tokens.
 */

export type UserFocusKind = 'plugin' | 'skill' | 'connector'

export type UserFocusPrefix = {
  kind: UserFocusKind
  name: string
  /** Remaining user text after the leading token (may be empty). */
  body: string
}

/** True when the message is only a plugin mount/unmount control token. */
export function isPluginControlOnlyMessage(text: string): boolean {
  return /^@plugin:\S+\s*$/i.test(text.trim())
}

export function parseUserFocusPrefix(text: string): UserFocusPrefix | null {
  const trimmed = text.trimStart()
  if (!trimmed) return null

  const plugin = /^@plugin:([^\s]+)(?:\s+([\s\S]*))?$/i.exec(trimmed)
  if (plugin) {
    const rawName = plugin[1] ?? ''
    const lowered = rawName.toLowerCase()
    if (!rawName || lowered === 'off' || lowered === 'none') return null
    return {
      kind: 'plugin',
      name: rawName,
      body: (plugin[2] ?? '').replace(/^\s+/, '')
    }
  }

  const skill = /^\/([^\s/@]+)(?:\s+([\s\S]*))?$/.exec(trimmed)
  if (skill) {
    return {
      kind: 'skill',
      name: skill[1] ?? '',
      body: (skill[2] ?? '').replace(/^\s+/, '')
    }
  }

  const connector = /^@([^\s]+)(?:\s+([\s\S]*))?$/.exec(trimmed)
  if (connector) {
    return {
      kind: 'connector',
      name: connector[1] ?? '',
      body: (connector[2] ?? '').replace(/^\s+/, '')
    }
  }

  return null
}

/** Rebuild wire-format text from a parsed focus chip + edited body. */
export function composeUserFocusMessage(focus: UserFocusPrefix, body: string): string {
  const trimmed = body.trim()
  if (focus.kind === 'plugin') {
    return trimmed ? `@plugin:${focus.name} ${trimmed}` : `@plugin:${focus.name}`
  }
  if (focus.kind === 'skill') {
    return trimmed ? `/${focus.name} ${trimmed}` : `/${focus.name}`
  }
  return trimmed ? `@${focus.name} ${trimmed}` : `@${focus.name}`
}
