import { describe, expect, it } from 'vitest'
import {
  skillDiscoveryRoots,
  skillRootFromMdPath,
  skillSourceFromPath,
  skillSourceIconKey,
  skillSourceTagFromPath
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
