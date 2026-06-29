const REASONING_OMITTED_LINE_RE = /^\s*\(reasoning omitted\)\s*$/i
const REASONING_OMITTED_INLINE_RE = /\(reasoning omitted\)/gi

export function sanitizeReasoningPlaceholders(text: string): string {
  return text
    .split(/\r?\n/)
    .filter((line) => !REASONING_OMITTED_LINE_RE.test(line))
    .join('\n')
    .replace(REASONING_OMITTED_INLINE_RE, '')
    .trim()
}
