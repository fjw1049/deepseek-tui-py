import { isMaterialRecognizedFile } from './file-icon'

export type ComposerPathMention = {
  start: number
  end: number
  path: string
  line?: number
  endLine?: number
}

export type CodeFenceInfo = {
  language: string
  filePath?: string
  lineStart?: number
  lineEnd?: number
}

const MENTION_RE = /@(?:"([^"]+)"|([^\s]+?))(?::(\d+)(?:-(\d+))?)?(?=\s|$)/g
const FENCE_RANGE_RE = /^(\d+):(\d+):(.+)$/

export function basenameOfPath(path: string): string {
  const trimmed = path.replace(/[\\/]+$/, '')
  const parts = trimmed.split(/[\\/]/)
  return parts[parts.length - 1] || trimmed
}

export function looksLikeFilePath(value: string): boolean {
  const path = value.trim()
  if (!path || path.startsWith('plugin:') || path.includes('://')) return false
  if (path.includes('/') || path.includes('\\')) return true
  return isMaterialRecognizedFile(path)
}

const FILE_EXTENSION_RE = /\.[A-Za-z0-9][A-Za-z0-9+_-]{0,19}$/

export function classifyWorkspacePath(
  value: string,
  statKind?: 'file' | 'directory'
): 'file' | 'directory' {
  const path = value.trim()
  if (!path) return 'file'
  if (path.endsWith('/') || path.endsWith('\\')) return 'directory'
  const base = basenameOfPath(path)
  const looksLikeFile =
    isMaterialRecognizedFile(path) ||
    isMaterialRecognizedFile(base) ||
    FILE_EXTENSION_RE.test(base)
  if (looksLikeFile) return 'file'
  if (statKind === 'file' || statKind === 'directory') return statKind
  return 'directory'
}

export function looksLikeDirectoryPath(value: string, statKind?: 'file' | 'directory'): boolean {
  return classifyWorkspacePath(value, statKind) === 'directory'
}

export function formatFileLineRange(line?: number, endLine?: number): string {
  if (!line || line < 1) return ''
  if (endLine && endLine >= 1 && endLine !== line) return `:${line}–${endLine}`
  return `:${line}`
}

export function parseComposerPathMentions(text: string): ComposerPathMention[] {
  const mentions: ComposerPathMention[] = []
  MENTION_RE.lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = MENTION_RE.exec(text)) !== null) {
    const path = (match[1] ?? match[2] ?? '').trim()
    if (!looksLikeFilePath(path)) continue
    const line = match[3] ? Number.parseInt(match[3], 10) : undefined
    const endLine = match[4] ? Number.parseInt(match[4], 10) : undefined
    mentions.push({
      start: match.index,
      end: match.index + match[0].length,
      path,
      ...(line && Number.isFinite(line) && line > 0 ? { line } : {}),
      ...(endLine && Number.isFinite(endLine) && endLine > 0 ? { endLine } : {})
    })
  }
  return mentions
}

export function parseCodeFenceInfo(raw: string): CodeFenceInfo {
  const info = raw.trim()
  if (!info) return { language: '' }

  const ranged = info.match(FENCE_RANGE_RE)
  if (ranged?.[1] && ranged[2] && ranged[3]) {
    const filePath = ranged[3].trim()
    const lineStart = Number.parseInt(ranged[1], 10)
    const lineEnd = Number.parseInt(ranged[2], 10)
    return {
      language: '',
      filePath,
      ...(Number.isFinite(lineStart) && lineStart > 0 ? { lineStart } : {}),
      ...(Number.isFinite(lineEnd) && lineEnd > 0 ? { lineEnd } : {})
    }
  }

  if (looksLikeFilePath(info)) {
    return { language: '', filePath: info }
  }

  return { language: info }
}
