import { describe, expect, it, vi } from 'vitest'

// The provider module does `import * as monaco`, whose top-level code touches
// `window`. We only exercise the pure scan logic + legend here, so stub monaco
// out entirely (same trick as workspace-monaco-models.test.ts).
vi.mock('monaco-editor', () => ({ languages: {} }))

import {
  PYTHON_SEMANTIC_LEGEND,
  provideSemanticTokens
} from './monaco-python-semantic-tokens'
import type { editor as MonacoEditor } from 'monaco-editor'

// Decoded token: [line, char, length, typeName, modifiers]
type Tok = [number, number, number, string, string[]]

function decode(data: Uint32Array): Tok[] {
  const out: Tok[] = []
  let line = 0
  let char = 0
  for (let i = 0; i < data.length; i += 5) {
    line += data[i]
    char = data[i] === 0 && i > 0 ? char + data[i + 1] : data[i + 1]
    if (data[i] !== 0) char = data[i + 1]
    const mods: string[] = []
    const m = data[i + 4]
    PYTHON_SEMANTIC_LEGEND.tokenModifiers.forEach((name, idx) => {
      if (m & (1 << idx)) mods.push(name)
    })
    out.push([line, char, data[i + 2], PYTHON_SEMANTIC_LEGEND.tokenTypes[data[i + 3]], mods])
  }
  return out
}

function mockModel(lines: string[]): MonacoEditor.ITextModel {
  return {
    getLineCount: () => lines.length,
    getLineContent: (n: number) => lines[n - 1] ?? ''
  } as unknown as MonacoEditor.ITextModel
}

const SOURCE = [
  'def looks_like_source_path(path: str, *, workspace: Path | None = None) -> bool:',
  '    raw = path.strip()',
  '    if not raw or raw in ("-", "/dev/null", "/dev/stdin", "/dev/stdout"):',
  '        return False',
  '    if is_allowlisted_path(raw, workspace=workspace):',
  '        return False',
  '    lower = raw.replace("\\\\", "/").lower()',
  '    if any(lower.endswith(s) for s in _SOURCE_SUFFIXES):',
  '        return True',
  '    return False',
  '',
  '@cached',
  'def _extract_redirect_targets(command: str) -> list[str]:',
  '    targets: list[str] = []',
  '    for match in _REDIRECT_WRITE.finditer(command):',
  '        targets.append(match.group(2))',
  '    return targets'
]

describe('python semantic tokens', () => {
  it('colors def names, calls, builtins, decorators and self/cls', () => {
    const result = provideSemanticTokens(mockModel(SOURCE))
    const toks = decode((result as { data: Uint32Array }).data)
    const byText = toks.map((t) => ({
      text: SOURCE[t[0]].slice(t[1], t[1] + t[2]),
      type: t[3],
      mods: t[4]
    }))

    const defName = byText.find((t) => t.text === 'looks_like_source_path')
    expect(defName?.type).toBe('function')
    expect(defName?.mods).toContain('declaration')

    const defName2 = byText.find((t) => t.text === '_extract_redirect_targets')
    expect(defName2?.type).toBe('function')
    expect(defName2?.mods).toContain('declaration')

    // builtin call -> macro.defaultLibrary
    const anyCall = byText.find((t) => t.text === 'any')
    expect(anyCall?.type).toBe('macro')
    expect(anyCall?.mods).toContain('defaultLibrary')

    // plain function call -> function (no declaration)
    const stripCall = byText.find((t) => t.text === 'strip')
    expect(stripCall?.type).toBe('function')
    expect(stripCall?.mods).not.toContain('declaration')

    const isAllow = byText.find((t) => t.text === 'is_allowlisted_path')
    expect(isAllow?.type).toBe('function')

    // decorator
    const decor = byText.find((t) => t.text === 'cached')
    expect(decor?.type).toBe('decorator')

    // method calls on objects
    expect(byText.some((t) => t.text === 'append' && t.type === 'function')).toBe(true)
    expect(byText.some((t) => t.text === 'finditer' && t.type === 'function')).toBe(true)
    expect(byText.some((t) => t.text === 'group' && t.type === 'function')).toBe(true)
  })

  it('does not color keywords even when followed by paren', () => {
    const lines = ['if (x):', '    return None']
    const result = provideSemanticTokens(mockModel(lines))
    const toks = decode((result as { data: Uint32Array }).data)
    const named = toks.map((t) => lines[t[0]].slice(t[1], t[1] + t[2]))
    expect(named).not.toContain('if')
    expect(named).not.toContain('return')
  })

  it('colors self/cls first parameter of a method', () => {
    const result = provideSemanticTokens(mockModel(['class C:', '    def meth(self, x):', '        return x']))
    const toks = decode((result as { data: Uint32Array }).data)
    const lines = ['class C:', '    def meth(self, x):', '        return x']
    const named = toks.map((t) => ({ text: lines[t[0]].slice(t[1], t[1] + t[2]), type: t[3] }))
    expect(named.some((n) => n.text === 'C' && n.type === 'class')).toBe(true)
    expect(named.some((n) => n.text === 'meth' && n.type === 'function')).toBe(true)
    expect(named.some((n) => n.text === 'self' && n.type === 'parameter')).toBe(true)
  })
})
