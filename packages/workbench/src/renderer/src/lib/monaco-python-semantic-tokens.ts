import * as monaco from 'monaco-editor'

// Monaco's built-in Python tokenizer is Monarch-grade: it colors keywords,
// strings, numbers and comments, but every name — function call, definition,
// builtin, parameter — collapses to one `identifier` token and stays the
// default foreground. That is why light mode looks nearly monochrome next to
// codex (VS Code engine + TextMate + semantic tokens). This provider adds the
// name-level coloring Monarch can't, so both themes reach codex richness.
//
// ponytail: regex scan, not a real parser — fooled by names inside multiline
// strings or unusual syntax. Acceptable for editor coloring; upgrade to a
// tree-sitter/ LSP-backed provider only if mis-coloring becomes visible.

export const PYTHON_SEMANTIC_LEGEND: monaco.languages.SemanticTokensLegend = {
  tokenTypes: ['function', 'method', 'macro', 'decorator', 'parameter', 'class'],
  tokenModifiers: ['declaration', 'defaultLibrary']
}

const TT = {
  function: 0,
  method: 1,
  macro: 2,
  decorator: 3,
  parameter: 4,
  class: 5
} as const
const TM = { declaration: 1, defaultLibrary: 2 } as const

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

const NAME = /[A-Za-z_]\w*/

// def <name>(  /  class <name>
const DEF_RE = /^[ \t]*(?:async[ \t]+)?def[ \t]+([A-Za-z_]\w*)[ \t]*\(/
const CLASS_RE = /^[ \t]*class[ \t]+([A-Za-z_]\w*)/
// @<name>  (decorator; dotted attrs left uncolored)
const DECOR_RE = /^[ \t]*@[ \t]*([A-Za-z_]\w*)/
// def foo(<self>, ...): first param of a method -> `parameter`
const FIRST_PARAM_RE = /\([ \t]*([A-Za-z_]\w*)[ \t]*[,)]/

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

  for (let i = 1; i <= model.getLineCount(); i++) {
    const text = model.getLineContent(i)
    const lineIdx = i - 1

    const defMatch = DEF_RE.exec(text)
    if (defMatch?.[1]) {
      const start = defMatch.index + defMatch[0].indexOf(defMatch[1])
      ;[prevLine, prevChar] = encode(data, prevLine, prevChar, lineIdx, start, defMatch[1].length, TT.function, TM.declaration)
      // color the first parameter (self/cls) of a method definition.
      // params already starts at the `(` (defMatch[0] ends with it), so fp.index
      // is the offset within `text` from that paren — no extra +1.
      const params = text.slice(defMatch[0].length - 1)
      const fp = FIRST_PARAM_RE.exec(params)
      if (fp?.[1] && (fp[1] === 'self' || fp[1] === 'cls')) {
        const pStart = defMatch[0].length - 1 + fp.index + 1
        ;[prevLine, prevChar] = encode(data, prevLine, prevChar, lineIdx, pStart, fp[1].length, TT.parameter, 0)
      }
      continue
    }

    const classMatch = CLASS_RE.exec(text)
    if (classMatch?.[1]) {
      const start = classMatch.index + classMatch[0].indexOf(classMatch[1])
      ;[prevLine, prevChar] = encode(data, prevLine, prevChar, lineIdx, start, classMatch[1].length, TT.class, TM.declaration)
      continue
    }

    const decorMatch = DECOR_RE.exec(text)
    if (decorMatch?.[1]) {
      const start = decorMatch.index + decorMatch[0].indexOf(decorMatch[1])
      ;[prevLine, prevChar] = encode(data, prevLine, prevChar, lineIdx, start, decorMatch[1].length, TT.decorator, 0)
      continue
    }

    // Function calls and bare builtins: walk every name on the line.
    // A name immediately followed by `(` is a call; builtins color even bare.
    let m: RegExpExecArray | null
    NAME.lastIndex = 0
    const re = new RegExp(NAME.source, 'g')
    while ((m = re.exec(text)) !== null) {
      const name = m[0]
      const after = text[m.index + name.length]
      const isCall = after === '('
      const isBuiltin = BUILTINS.has(name)
      if (!isCall && !isBuiltin) continue
      // skip keywords the call-regex would otherwise catch (e.g. `if(`)
      if (/^(def|class|if|elif|else|for|while|return|import|from|as|try|except|finally|with|lambda|pass|break|continue|raise|yield|assert|del|in|is|not|and|or|global|nonlocal|async|await)$/.test(name)) continue
      const type = isBuiltin ? TT.macro : TT.function
      const modifiers = isBuiltin ? TM.defaultLibrary : 0
      ;[prevLine, prevChar] = encode(data, prevLine, prevChar, lineIdx, m.index, name.length, type, modifiers)
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
