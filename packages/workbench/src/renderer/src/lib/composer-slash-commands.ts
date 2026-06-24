export const COMPOSER_ACTION_COMMAND_IDS = [
  'model',
  'context',
  'compact',
  'mcp',
  'skills',
  'diff',
  'fork',
  'hooks'
] as const

export type ComposerActionCommandId = (typeof COMPOSER_ACTION_COMMAND_IDS)[number]

export type ParsedComposerCommand = {
  id: ComposerActionCommandId
  args: string
}

export function parseComposerActionCommand(input: string): ParsedComposerCommand | null {
  const trimmed = input.trim()
  if (!trimmed.startsWith('/')) return null
  const [token, ...rest] = trimmed.slice(1).split(/\s+/)
  const id = token.toLowerCase()
  if (!COMPOSER_ACTION_COMMAND_IDS.includes(id as ComposerActionCommandId)) return null
  return { id: id as ComposerActionCommandId, args: rest.join(' ') }
}

export function isUnknownComposerSlashCommand(input: string): boolean {
  const trimmed = input.trim()
  return trimmed.startsWith('/') && trimmed.length > 1 && parseComposerActionCommand(trimmed) === null
}
