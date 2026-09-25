import * as monaco from 'monaco-editor'

// Name-level hints complement Monaco's Python syntax colors.
// ponytail: lexical heuristics, not symbol resolution. PascalCase names are
// treated as types; strings/comments are masked before inspecting names.

export const PYTHON_SEMANTIC_LEGEND: monaco.languages.SemanticTokensLegend = {
  tokenTypes: ['function', 'method', 'macro', 'decorator', 'parameter', 'class', 'variable'],
  tokenModifiers: ['declaration', 'defaultLibrary', 'readonly']
}

const TT = {
  function: 0,
  method: 1,
  macro: 2,
  decorator: 3,
  parameter: 4,
  class: 5,
  constant: 6
} as const
const TM = { declaration: 1, defaultLibrary: 2, readonly: 4 } as const

// Builtins colored as `macro` (blue). Kept small — the common ones a reader
// expects to pop. Add here when a frequently-used builtin stays flat.
const BUILTINS = new Set([
  'print', 'len', 'range', 'sorted', 'reversed', 'enumerate', 'zip', 'map', 'filter',
  'sum', 'min', 'max', 'abs', 'round', 'int', 'float', 'str', 'list', 'dict', 'set',
  'tuple', 'bool', 'type', 'isinstance', 'issubclass', 'hasattr', 'getattr', 'setattr',
  'open', 'input', 'id', 'hash', 'repr', 'format', 'iter', 'next', 'any', 'all',
  'super', 'object', 'staticmethod', 'classmethod', 'property', 'ValueError',
  'TypeError', 'KeyError', 'IndexError', 'AttributeError', 'RuntimeError',
  'Exception', 'BaseException', 'NotImplementedError', 'StopIteration'
])

// Preserve offsets and line breaks while excluding comments and literals.
// Triple-quoted strings may span lines or remain open while the user types.
const NON_CODE = /#[^\r\n]*|'''[\s\S]*?(?:'''|$)|"""[\s\S]*?(?:"""|$)|'(?:\\[^]|[^'\\\r\n])*'?|"(?:\\[^]|[^"\\\r\n])*"?/g
const KEYWORDS = new Set('def class if elif else for while return import from as try except finally with lambda pass break continue raise yield assert del in is not and or global nonlocal async await True False None'.split(' '))

function encode(
  builder: number[],
  prevLine: number,
  prevChar: number,
  line: number,
  char: number,
  length: number,
  type: number,
  modifiers: number
): [number, number] {
  builder.push(line - prevLine, char - (line === prevLine ? prevChar : 0), length, type, modifiers)
  return [line, char]
}

export function provideSemanticTokens(
  model: monaco.editor.ITextModel
): monaco.languages.ProviderResult<monaco.languages.SemanticTokens> {
  const data: number[] = []
  let prevLine = 0
  let prevChar = 0

  const source = Array.from({ length: model.getLineCount() }, (_, i) => model.getLineContent(i + 1)).join('\n')
  const lines = source.replace(NON_CODE, (value) => value.replace(/[^\r\n]/g, ' ')).split('\n')
  for (const [lineIdx, text] of lines.entries()) {
    const declaration = /^(\s*(?:async\s+)?(?:def|class)\s+)([A-Za-z_]\w*)/.exec(text)
    const declarationStart = declaration?.[1]?.length
    const functionHeader = /^\s*(?:async\s+)?def\s/.test(text)
    const decorator = /^\s*@/.test(text)
    for (const match of text.matchAll(/[A-Za-z_]\w*/g)) {
      const name = match[0]
      if (KEYWORDS.has(name)) continue
      const start = match.index!
      const before = text.slice(0, start)
      const after = text.slice(start + name.length)
      let type: number
      let modifiers = 0
      if (start === declarationStart) {
        type = functionHeader ? TT.function : TT.class
        modifiers = TM.declaration
      } else if (decorator && /^\s*(?:\.|\(|$)/.test(after) && !before.includes('(')) {
        type = TT.decorator
      } else if (functionHeader && /[(,]\s*\*{0,2}$/.test(before) && /^\s*[:,)=]/.test(after)) {
        type = TT.parameter
      } else if (/^[A-Z][A-Z0-9_]+$/.test(name)) {
        type = TT.constant
        modifiers = TM.readonly
      } else if (/^[A-Z][a-zA-Z0-9_]*$/.test(name)) {
        type = TT.class
      } else if (BUILTINS.has(name) && !/\.\s*$/.test(before)) {
        type = TT.macro
        modifiers = TM.defaultLibrary
      } else if (/^\s*\(/.test(after)) {
        type = TT.function
      } else if (name === 'self' || name === 'cls') {
        type = TT.parameter
      } else {
        continue
      }
      ;[prevLine, prevChar] = encode(data, prevLine, prevChar, lineIdx, start, name.length, type, modifiers)
    }
  }

  return { data: new Uint32Array(data) }
}

let registered = false

export function registerPythonSemanticTokens(): monaco.IDisposable[] {
  if (registered) return []
  registered = true
  return [
    monaco.languages.registerDocumentSemanticTokensProvider('python', {
      getLegend: () => PYTHON_SEMANTIC_LEGEND,
      provideDocumentSemanticTokens: (model) => provideSemanticTokens(model),
      releaseDocumentSemanticTokens: () => undefined
    })
  ]
}
