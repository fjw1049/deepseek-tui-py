import { describe, expect, it, vi } from 'vitest'

// The provider module does `import * as monaco`, whose top-level code touches
// `window`. We only exercise the pure scan logic + legend here, so stub monaco
// out entirely (same trick as workspace-monaco-models.test.ts).
vi.mock('monaco-editor', () => ({ languages: {} }))

import {
  LEXICAL_PROFILES,
  LEXICAL_SEMANTIC_LEGEND,
  provideSemanticTokens
} from './monaco-lexical-semantic-tokens'
import type { editor as MonacoEditor } from 'monaco-editor'

type Tok = [number, number, number, string, number]

function decode(data: Uint32Array): Tok[] {
  const out: Tok[] = []
  let line = 0
  let char = 0
  for (let i = 0; i < data.length; i += 5) {
    const [dLine, dChar, length, type, modifiers] = [
      data[i], data[i + 1], data[i + 2], data[i + 3], data[i + 4]
    ]
    line += dLine
    char = dLine === 0 ? char + dChar : dChar
    out.push([line, char, length, LEXICAL_SEMANTIC_LEGEND.tokenTypes[type], modifiers])
  }
  return out
}

function mockModel(lines: string[], languageId: string): MonacoEditor.ITextModel {
  return {
    getLanguageId: () => languageId,
    getLineCount: () => lines.length,
    getLineContent: (n: number) => lines[n - 1] ?? ''
  } as unknown as MonacoEditor.ITextModel
}

/** [text, typeName, modifierNames] for every token of a sample. */
function tokensIn(lines: string[], languageId: string): [string, string, string[]][] {
  const result = provideSemanticTokens(mockModel(lines, languageId))
  if (result === null) throw new Error(`no provider for ${languageId}`)
  return decode((result as { data: Uint32Array }).data).map(([line, col, length, type, mods]) => [
    lines[line].slice(col, col + length),
    type,
    LEXICAL_SEMANTIC_LEGEND.tokenModifiers.filter((_, idx) => mods & (1 << idx))
  ])
}


const tokenOf = (lines: string[], languageId: string, text: string): [string, string] | undefined => {
  const hit = tokensIn(lines, languageId)
    .filter((t) => t[0] === text)
    .map((t) => [t[0], t[1]] as [string, string])
  return hit[0]
}

describe('lexical semantic tokens', () => {
  it('registers a profile for every mainstream language', () => {
    for (const language of ['python', 'go', 'rust', 'c', 'cpp', 'java', 'javascript', 'typescript']) {
      expect(LEXICAL_PROFILES[language]).toBeDefined()
    }
  })

  it('declines languages without a profile', () => {
    expect(provideSemanticTokens(mockModel(['{"a": 1}'], 'json'))).toBeNull()
  })

  it('excludes comments and strings, and only in the family they belong to', () => {
    const python = [
      '# print(x)',
      'text = "print(x)"',
      'doc = """',
      'class Fake:',
      'print(x)',
      '"""',
      "text = 'unfinished print(x)"
    ]
    expect(tokensIn(python, 'python')).toEqual([])

    // `#` opens a preprocessor directive here, so it must not blank the line.
    expect(tokenOf(['#define MAX 3'], 'c', 'MAX')).toEqual(['MAX', 'variable'])
    const c = ['int x = 1; // helper(y)', '/* helper(y) */']
    expect(tokensIn(c, 'c').map(([text]) => text)).toEqual(['int'])
    expect(tokensIn(['-- helper(y)', "local s = 'helper(y)'"], 'lua')).toEqual([])
    expect(tokensIn(['# helper(y)'], 'shell')).toEqual([])
  })

  it('colors Python definitions, parameters, types, constants and builtins', () => {
    const lines = [
      'def f(value: SessionState, count: int = 1):',
      '    return MAX_ITEMS, value, len (value)',
      '@cached',
      'class C:',
      '    def meth(self, x):',
      '        return x'
    ]
    const tokens = tokensIn(lines, 'python')
    expect(tokens).toContainEqual(['f', 'function', ['declaration']])
    expect(tokenOf(lines, 'python', 'value')).toEqual(['value', 'parameter'])
    expect(tokenOf(lines, 'python', 'count')).toEqual(['count', 'parameter'])
    // Types read as types, builtin *functions* as builtins: `int` and `len`
    // used to share one blue.
    expect(tokenOf(lines, 'python', 'SessionState')).toEqual(['SessionState', 'class'])
    expect(tokenOf(lines, 'python', 'int')).toEqual(['int', 'class'])
    expect(tokenOf(lines, 'python', 'len')).toEqual(['len', 'macro'])
    expect(tokenOf(lines, 'python', 'MAX_ITEMS')).toEqual(['MAX_ITEMS', 'variable'])
    expect(tokenOf(lines, 'python', 'cached')).toEqual(['cached', 'decorator'])
    expect(tokenOf(lines, 'python', 'C')).toEqual(['C', 'class'])
    // `self` is the language's own word, so it outranks the signature it sits
    // in — and matches the `variable.language` slot chat blocks already use.
    expect(tokenOf(lines, 'python', 'self')).toEqual(['self', 'variable'])
    expect(tokens).toContainEqual(['self', 'variable', ['readonly']])
    expect(tokenOf(lines, 'python', 'if')).toBeUndefined()
  })

  it('colors module names, keyword arguments and bound functions', () => {
    expect(tokenOf(['package main'], 'go', 'main')).toEqual(['main', 'namespace'])
    expect(tokenOf(['import os'], 'python', 'os')).toEqual(['os', 'namespace'])
    expect(tokenOf(['use std::io;'], 'rust', 'std')).toEqual(['std', 'namespace'])
    // `using namespace std;` — the word never becomes a namespace itself.
    expect(tokenOf(['using namespace std;'], 'cpp', 'namespace')).toBeUndefined()

    const call = ['result = parse( 1 , timeout=5)']
    expect(tokenOf(call, 'python', 'timeout')).toEqual(['timeout', 'parameter'])
    // An assignment is not a keyword argument.
    expect(tokenOf(['total = sum(values)'], 'python', 'total')).toBeUndefined()

    const bound = ['const render = (node) => node', 'const later = function () {}']
    expect(tokenOf(bound, 'javascript', 'render')).toEqual(['render', 'function'])
    expect(tokenOf(bound, 'javascript', 'later')).toEqual(['later', 'function'])
    expect(tokenOf(bound, 'javascript', 'node')).toEqual(['node', 'parameter'])
  })

  it('handles the families added after the C-like and shell ones', () => {
    // proto: `message`/`rpc` are its declaration keywords.
    expect(tokenOf(['message Point {'], 'proto', 'Point')).toEqual(['Point', 'class'])
    expect(tokenOf(['rpc Get(Req) returns (Res);'], 'proto', 'Get')).toEqual(['Get', 'function'])

    // `;` comments (lisp family) and `#`/`//` comments (hcl) are masked too.
    expect(tokensIn(['; helper(x)'], 'scheme')).toEqual([])
    expect(tokensIn(['(defn f [x] x)'], 'clojure')).toContainEqual(['f', 'function', ['declaration']])
    expect(tokensIn(['# helper(x)', '// helper(y)'], 'hcl')).toEqual([])
    expect(tokensIn(['# install deps'], 'dockerfile')).toEqual([])
  })

  it('colors C-family definitions, members and type words', () => {
    const lines = [
      'int add(int a, int b) {',
      '  printf("%d", a);',
      '  return helper.count + compute(a);',
      '}'
    ]
    const tokens = tokensIn(lines, 'c')
    expect(tokens).toContainEqual(['add', 'function', ['declaration']])
    expect(tokenOf(lines, 'c', 'a')).toEqual(['a', 'parameter'])
    expect(tokenOf(lines, 'c', 'int')).toEqual(['int', 'class'])
    expect(tokenOf(lines, 'c', 'printf')).toEqual(['printf', 'function'])
    // Plain locals stay ink; only members and call sites are picked out.
    expect(tokenOf(lines, 'c', 'helper')).toBeUndefined()
    expect(tokenOf(lines, 'c', 'count')).toEqual(['count', 'variable'])
    expect(tokenOf(lines, 'c', 'compute')).toEqual(['compute', 'function'])
  })

  it('colors Go, Rust and JavaScript definitions', () => {
    const go = ['func (s *Server) handle(w Writer) error {', '  return len(s.buf)']
    expect(tokenOf(go, 'go', 'handle')).toEqual(['handle', 'function'])
    expect(tokenOf(go, 'go', 'Writer')).toEqual(['Writer', 'class'])
    expect(tokenOf(go, 'go', 'len')).toEqual(['len', 'macro'])
    expect(tokenOf(go, 'go', 'buf')).toEqual(['buf', 'variable'])

    const rust = ['pub fn parse(input: &str) -> Result<Doc, Error> {', '  println!("{}", MAX)']
    expect(tokenOf(rust, 'rust', 'parse')).toEqual(['parse', 'function'])
    expect(tokenOf(rust, 'rust', 'println')).toEqual(['println', 'macro'])
    expect(tokenOf(rust, 'rust', 'input')).toEqual(['input', 'parameter'])
    expect(tokenOf(rust, 'rust', 'str')).toEqual(['str', 'class'])
    expect(tokenOf(rust, 'rust', 'Doc')).toEqual(['Doc', 'class'])

    const js = [
      '@Component({ selector: "app" })',
      'function render(node, depth) {',
      '  return document.querySelector(node).innerHTML'
    ]
    expect(tokenOf(js, 'javascript', 'Component')).toEqual(['Component', 'decorator'])
    expect(tokenOf(js, 'javascript', 'render')).toEqual(['render', 'function'])
    expect(tokenOf(js, 'javascript', 'depth')).toEqual(['depth', 'parameter'])
    expect(tokenOf(js, 'javascript', 'querySelector')).toEqual(['querySelector', 'function'])
    expect(tokenOf(js, 'javascript', 'innerHTML')).toEqual(['innerHTML', 'variable'])
  })

  it('does not color names inside strings, comments or quotes for any family', () => {
    const lines = ['const label = `helper(x)` // helper(y)', "const other = 'helper(z)'"]
    expect(tokensIn(lines, 'typescript')).toEqual([])
  })
})
