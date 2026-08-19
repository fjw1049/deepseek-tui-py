/** Where a SKILL.md was loaded from — drives the Skills list icon. */

export const SKILL_SOURCES = [
  'claude',
  'codex',
  'cursor',
  'qwen',
  'gemini',
  'codebuddy',
  'own',
  'opencode'
] as const
export type SkillSource = (typeof SKILL_SOURCES)[number]

export type SkillSourceTag = SkillSource

const WORKSPACE_SKILL_RELATIVE_ROOTS = [
  ['.agents', 'skills'],
  ['.agent', 'skills'],
  ['skills'],
  ['.deepseek', 'skills'],
  ['.opencode', 'skills'],
  ['.claude', 'skills'],
  ['.cursor', 'skills'],
  ['.codex', 'skills'],
  ['.qwen', 'skills'],
  ['.gemini', 'skills'],
  ['.codebuddy', 'skills']
] as const

const GLOBAL_SKILL_ROOTS = [
  '~/.agents/skills',
  '~/.agent/skills',
  '~/.claude/skills',
  '~/.cursor/skills',
  '~/.codex/skills',
  '~/.qwen/skills',
  '~/.gemini/skills',
  '~/.codebuddy/skills'
] as const

function joinSkillRoot(base: string, parts: readonly string[]): string {
  const prefix = base.replace(/[/\\]+$/, '')
  const sep = base.includes('\\') && !base.includes('/') ? '\\' : '/'
  return [prefix, ...parts].join(sep)
}

/**
 * Classify a skill file/folder path by its ecosystem directory.
 *
 * Scans right-to-left so the directory closest to the SKILL.md wins: a
 * workspace nested under another ecosystem's home (e.g.
 * `~/.claude/projects/foo/.deepseek/skills/x/SKILL.md`) belongs to the
 * inner `.deepseek`, not the outer `.claude` ancestor.
 */
export function skillSourceFromPath(filePath: string): SkillSource {
  const parts = filePath.replace(/\\/g, '/').split('/')
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const lower = parts[index].toLowerCase()
    if (lower === '.claude') return 'claude'
    if (lower === '.codex') return 'codex'
    if (lower === '.cursor' || lower === '.agent' || lower === '.agents') return 'cursor'
    if (lower === '.qwen') return 'qwen'
    if (lower === '.gemini') return 'gemini'
    if (lower === '.codebuddy') return 'codebuddy'
    if (lower === '.opencode') return 'opencode'
    if (lower === '.deepseek') return 'own'
  }
  return 'own'
}

/** Catalogue key for the same brand tiles used by the model picker. */
export function skillSourceIconKey(source: SkillSource): string {
  if (source === 'opencode') return 'own'
  return source
}

export function skillSourceTagFromPath(filePath: string): SkillSourceTag {
  return skillSourceFromPath(filePath)
}

/** Directory that contains `<name>/SKILL.md`. */
export function skillRootFromMdPath(skillMdPath: string): string {
  const trimmed = skillMdPath.replace(/[/\\]+$/, '')
  const match = trimmed.match(/^(.*)[/\\][^/\\]+[/\\]SKILL\.md$/i)
  return match?.[1] ?? trimmed
}

/**
 * Every skill root the Workbench should list.
 * ``ownSkillsDir`` is the live DeepSeek install path (respects DEEPSEEK_HOME).
 */
export function skillDiscoveryRoots(ownSkillsDir: string, workspace?: string | null): string[] {
  const roots: string[] = []
  const seen = new Set<string>()
  const add = (value: string): void => {
    const key = value.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
    if (!key || seen.has(key)) return
    seen.add(key)
    roots.push(value)
  }
  const workspaceRoot = workspace?.trim()
  if (workspaceRoot) {
    for (const parts of WORKSPACE_SKILL_RELATIVE_ROOTS) {
      add(joinSkillRoot(workspaceRoot, parts))
    }
  }
  for (const root of GLOBAL_SKILL_ROOTS) add(root)
  add(ownSkillsDir)
  return roots
}
