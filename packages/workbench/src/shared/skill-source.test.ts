import { describe, expect, it } from 'vitest'
import {
  dedupeSkillsById,
  skillDiscoveryRoots,
  skillIdentityKey,
  skillRootFromMdPath,
  skillSourceFromPath,
  skillSourceIconKey,
  skillSourceTagFromPath,
  uniqueSkillSourcePaths
} from './skill-source'

describe('skillSourceFromPath', () => {
  it('maps ecosystem folders to brand icons', () => {
    expect(skillSourceFromPath('/Users/me/.claude/skills/review/SKILL.md')).toBe('claude')
    expect(skillSourceFromPath('/Users/me/.codex/skills/pr/SKILL.md')).toBe('codex')
    expect(skillSourceFromPath('/Users/me/.cursor/skills/edit/SKILL.md')).toBe('cursor')
    expect(skillSourceFromPath('/Users/me/.agents/skills/browse/SKILL.md')).toBe('cursor')
    expect(skillSourceFromPath('/Users/me/.agent/skills/browse/SKILL.md')).toBe('cursor')
    expect(skillSourceFromPath('/Users/me/.deepseek/skills/mine/SKILL.md')).toBe('own')
    expect(skillSourceFromPath('/Users/me/.qwen/skills/writer/SKILL.md')).toBe('qwen')
    expect(skillSourceFromPath('/Users/me/.gemini/skills/search/SKILL.md')).toBe('gemini')
    expect(skillSourceFromPath('/tmp/proj/.codebuddy/skills/review/SKILL.md')).toBe('codebuddy')
    expect(skillSourceFromPath('/tmp/proj/.opencode/skills/x/SKILL.md')).toBe('opencode')
  })

  it('treats project-local and unknown paths as own', () => {
    expect(skillSourceFromPath('/tmp/proj/skills/local/SKILL.md')).toBe('own')
    expect(skillSourceFromPath('C:\\Users\\me\\.claude\\skills\\x\\SKILL.md')).toBe('claude')
  })

  it('lets the innermost ecosystem dir win over an outer ancestor', () => {
    expect(
      skillSourceFromPath('/Users/me/.claude/projects/foo/.deepseek/skills/mine/SKILL.md')
    ).toBe('own')
    expect(skillSourceFromPath('/Users/me/.cursor/work/proj/.claude/skills/review/SKILL.md')).toBe(
      'claude'
    )
    expect(
      skillSourceFromPath('C:\\Users\\me\\.claude\\proj\\.deepseek\\skills\\mine\\SKILL.md')
    ).toBe('own')
  })
})

describe('skillSourceTagFromPath', () => {
  it('labels .agents as cursor', () => {
    expect(skillSourceTagFromPath('/Users/me/.agents/skills/browse/SKILL.md')).toBe('cursor')
    expect(skillSourceTagFromPath('/Users/me/.cursor/skills/edit/SKILL.md')).toBe('cursor')
  })
})

describe('skillSourceIconKey', () => {
  it('uses the model-picker catalogue keys', () => {
    expect(skillSourceIconKey('claude')).toBe('claude')
    expect(skillSourceIconKey('codex')).toBe('codex')
    expect(skillSourceIconKey('cursor')).toBe('cursor')
    expect(skillSourceIconKey('qwen')).toBe('qwen')
    expect(skillSourceIconKey('gemini')).toBe('gemini')
    expect(skillSourceIconKey('codebuddy')).toBe('codebuddy')
    expect(skillSourceIconKey('own')).toBe('own')
    expect(skillSourceIconKey('opencode')).toBe('own')
  })
})

describe('skillRootFromMdPath', () => {
  it('strips the skill folder and SKILL.md', () => {
    expect(skillRootFromMdPath('/Users/me/.claude/skills/review/SKILL.md')).toBe(
      '/Users/me/.claude/skills'
    )
    expect(skillRootFromMdPath('C:\\Users\\me\\.codex\\skills\\pr\\SKILL.md')).toBe(
      'C:\\Users\\me\\.codex\\skills'
    )
  })
})

describe('skillDiscoveryRoots', () => {
  it('includes workspace ecosystems plus globals and the live DeepSeek dir', () => {
    const roots = skillDiscoveryRoots('~/.deepseek/skills', '/tmp/proj')
    expect(roots).toContain('/tmp/proj/.claude/skills')
    expect(roots).toContain('/tmp/proj/.codex/skills')
    expect(roots).toContain('/tmp/proj/.cursor/skills')
    expect(roots).toContain('/tmp/proj/.agents/skills')
    expect(roots).toContain('/tmp/proj/.qwen/skills')
    expect(roots).toContain('/tmp/proj/.gemini/skills')
    expect(roots).toContain('/tmp/proj/.codebuddy/skills')
    expect(roots).toContain('~/.claude/skills')
    expect(roots).toContain('~/.codex/skills')
    expect(roots).toContain('~/.qwen/skills')
    expect(roots).toContain('~/.gemini/skills')
    expect(roots).toContain('~/.codebuddy/skills')
    expect(roots).toContain('~/.deepseek/skills')
  })
})

describe('dedupeSkillsById', () => {
  it('keeps the first copy and records the rest', () => {
    const skills = [
      { id: 'open-knowledge-discovery', name: 'open-knowledge-discovery', path: '/Users/me/.agents/skills/open-knowledge-discovery/SKILL.md' },
      { id: 'open-knowledge-discovery', name: 'open-knowledge-discovery', path: '/Users/me/.claude/skills/open-knowledge-discovery/SKILL.md' },
      { id: 'open-knowledge-discovery', name: 'open-knowledge-discovery', path: '/Users/me/.cursor/skills/open-knowledge-discovery/SKILL.md' },
      { id: 'xlsx', name: 'xlsx', path: '/Users/me/.claude/skills/xlsx/SKILL.md' },
      { id: 'xlsx', name: 'xlsx', path: '/Users/me/.deepseek/skills/xlsx/SKILL.md' }
    ]
    const deduped = dedupeSkillsById(skills)
    expect(deduped.map((skill) => skill.path)).toEqual([
      '/Users/me/.agents/skills/open-knowledge-discovery/SKILL.md',
      '/Users/me/.claude/skills/xlsx/SKILL.md'
    ])
    expect(deduped[0]?.copies).toHaveLength(3)
    expect(deduped[1]?.copies).toHaveLength(2)
    expect(skillIdentityKey(deduped[0]!)).toBe('open-knowledge-discovery')
  })

  it('treats folder ids case-insensitively', () => {
    const deduped = dedupeSkillsById([
      { id: 'PDF', path: '/tmp/a/PDF/SKILL.md' },
      { id: 'pdf', path: '/tmp/b/pdf/SKILL.md' }
    ])
    expect(deduped).toHaveLength(1)
    expect(deduped[0]?.copies).toHaveLength(2)
  })
})

describe('uniqueSkillSourcePaths', () => {
  it('keeps one path per agent brand', () => {
    expect(
      uniqueSkillSourcePaths([
        '/Users/me/.claude/skills/xlsx/SKILL.md',
        '/Users/me/.claude/skills/xlsx-copy/SKILL.md',
        '/Users/me/.deepseek/skills/xlsx/SKILL.md'
      ])
    ).toEqual([
      '/Users/me/.claude/skills/xlsx/SKILL.md',
      '/Users/me/.deepseek/skills/xlsx/SKILL.md'
    ])
  })
})
