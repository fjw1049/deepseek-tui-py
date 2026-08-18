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

export function isGoalComposerSlashCommand(input: string): boolean {
  const trimmed = input.trim()
  if (!trimmed.startsWith('/')) return false
  const token = trimmed.slice(1).split(/\s+/)[0]?.toLowerCase() ?? ''
  return token === 'goal'
}

export function goalComposerSlashArgs(input: string): string {
  const trimmed = input.trim()
  if (!isGoalComposerSlashCommand(trimmed)) return ''
  return trimmed.replace(/^\/goal\s*/i, '')
}

export function shouldCreateGoalFromComposer(
  text: string,
  composerMode: string,
  currentGoal: unknown
): boolean {
  if (isGoalComposerSlashCommand(text)) return false
  return composerMode === 'goal' && currentGoal == null
}

export function isUnknownComposerSlashCommand(input: string): boolean {
  const trimmed = input.trim()
  if (!trimmed.startsWith('/') || trimmed.length <= 1) return false
  // Claude-style plugin commands use /<plugin>:<command> syntax.
  const token = trimmed.slice(1).split(/\s+/)[0]?.toLowerCase() ?? ''
  if (/^[^:\s]+:[^:\s]+$/.test(token)) return false
  if (token === 'goal') return false
  return parseComposerActionCommand(trimmed) === null
}
