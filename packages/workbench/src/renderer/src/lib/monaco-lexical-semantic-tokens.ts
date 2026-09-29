import * as monaco from 'monaco-editor'

// Name-level colors for mainstream languages.
//
// Monaco only ships Monarch (lexical) grammars, so an identifier is either a
// keyword or flat ink: `def parse(` and `result = parse(` look identical, and
// `MAX_RETRIES` reads like any other word. VS Code closes that gap with
// language-service semantic tokens; this is a lexical stand-in — declarations,
// call sites, types, constants, members and parameters guessed from shape and
// position.
//
// ponytail: lexical heuristics, not symbol resolution. Same confidence bar as
// the Python-only provider this replaces, now driven by a per-language profile.

export const LEXICAL_SEMANTIC_LEGEND: monaco.languages.SemanticTokensLegend = {
  // Slot 6 is named `variable` (the LSP name) but is emitted for members and
  // constants — the `readonly` modifier is what splits them apart in the theme
  // (`variable` → property ink, `variable.readonly` → constant ink).
  tokenTypes: [
    'function', 'method', 'macro', 'decorator', 'parameter', 'class', 'variable', 'namespace'
  ],
  tokenModifiers: ['declaration', 'defaultLibrary', 'readonly']
}

const TT = {
  function: 0,
  method: 1,
  macro: 2,
  decorator: 3,
  parameter: 4,
  class: 5,
  member: 6,
  namespace: 7
} as const
const TM = { declaration: 1, defaultLibrary: 2, readonly: 4 } as const

/**
 * Comment + string syntaxes per language family: `#` (shell, python…), `//`
 * (C-like), `--` (lua), `;` (lisp), and `#`-or-`//` (hcl/terraform).
 */
type Family = 'hash' | 'slash' | 'dash' | 'semi' | 'mixed'

type LanguageProfile = {
  family: Family
  /** Primitive type names — painted as types, not as calls. */
  types?: ReadonlySet<string>
  /** Builtin *functions* to paint as `macro`. Kept small on purpose. */
  builtins?: ReadonlySet<string>
  /** `@Name` annotations (Python/Java/C#/Kotlin/Swift/TS). */
  annotations?: boolean
  /** Rust `name!` macros. */
  bangMacros?: boolean
}

/** Types Python spells in lower case; the Pascal-cased ones read as classes. */
const PY_TYPES = new Set([
  'int', 'float', 'complex', 'str', 'bool', 'list', 'dict', 'set', 'frozenset',
  'tuple', 'bytes', 'bytearray', 'memoryview', 'object', 'type'
])
const PY_BUILTINS = new Set([
  'print', 'len', 'range', 'sorted', 'reversed', 'enumerate', 'zip', 'map', 'filter',
  'sum', 'min', 'max', 'abs', 'round', 'isinstance', 'issubclass', 'hasattr', 'getattr',
  'setattr', 'open', 'input', 'id', 'hash', 'repr', 'format', 'iter', 'next', 'any',
  'all', 'super', 'staticmethod', 'classmethod', 'property'
])
const GO_BUILTINS = new Set([
  'len', 'cap', 'make', 'new', 'append', 'copy', 'delete', 'close', 'panic',
  'recover', 'print', 'println', 'complex', 'real', 'imag', 'clear'
])
/** Primitive type names, painted like any other type rather than as calls. */
const TYPE_WORDS = new Set([
  'int', 'int8', 'int16', 'int32', 'int64', 'uint', 'uint8', 'uint16', 'uint32', 'uint64',
  'i8', 'i16', 'i32', 'i64', 'i128', 'u8', 'u16', 'u32', 'u64', 'u128', 'usize', 'isize',
  'f32', 'f64', 'float', 'float32', 'float64', 'double', 'long', 'short', 'char', 'byte',
  'rune', 'bool', 'boolean', 'string', 'str', 'void', 'unsigned', 'signed', 'size_t',
  'auto', 'error', 'any', 'unknown', 'never', 'object', 'symbol', 'bigint', 'number'
])

const HASH: LanguageProfile = { family: 'hash' }
const CLike: LanguageProfile = { family: 'slash', types: TYPE_WORDS }

/** Language id → profile. Registering here also registers the provider. */
export const LEXICAL_PROFILES: Record<string, LanguageProfile> = {
  python: { ...HASH, types: PY_TYPES, builtins: PY_BUILTINS, annotations: true },
  ruby: HASH,
  shell: HASH,
  perl: HASH,
  r: HASH,
  elixir: { ...HASH, annotations: true },
  dockerfile: HASH,
  graphql: HASH,
  powershell: HASH,
  lua: { family: 'dash' },
  go: { ...CLike, builtins: GO_BUILTINS },
  rust: { ...CLike, bangMacros: true },
  c: CLike,
  cpp: CLike,
  java: { ...CLike, annotations: true },
  csharp: { ...CLike, annotations: true },
  javascript: { ...CLike, annotations: true },
  typescript: { ...CLike, annotations: true },
  kotlin: { ...CLike, annotations: true },
  swift: { ...CLike, annotations: true },
  dart: { ...CLike, annotations: true },
  php: CLike,
  scala: { ...CLike, annotations: true },
  // Monaco's own ids for these two are `sol` and `proto`, not the names the
  // languages go by (`protobuf` is only an alias, and unknown ids fall back to
  // plaintext silently).
  sol: CLike,
  proto: CLike,
  'objective-c': { ...CLike, annotations: true },
  julia: { family: 'slash' },
  fsharp: { family: 'slash' },
  hcl: { family: 'mixed' },
  scheme: { family: 'semi' },
  clojure: { family: 'semi' }
}

// Preserve offsets and line breaks while blanking comments and literals, so a
// name inside a string never gets painted. Triple quotes may span lines or stay
// open mid-typing; `#` is a comment only outside the C-like family, because
// there it opens a preprocessor directive.
const MASK: Record<Family, RegExp> = {
  hash: /#[^\r\n]*|'''[\s\S]*?(?:'''|$)|"""[\s\S]*?(?:"""|$)|'(?:\\[^]|[^'\\\r\n])*'?|"(?:\\[^]|[^"\\\r\n])*"?/g,
  slash: /\/\/[^\r\n]*|\/\*[\s\S]*?(?:\*\/|$)|'(?:\\[^]|[^'\\\r\n])*'?|"(?:\\[^]|[^"\\\r\n])*"?|`(?:\\[^]|[^`\\])*`?/g,
  dash: /--[^\r\n]*|\{-[\s\S]*?(?:-\}|$)|\[\[[\s\S]*?(?:\]\]|$)|'(?:\\[^]|[^'\\\r\n])*'?|"(?:\\[^]|[^"\\\r\n])*"?/g,
  semi: /;[^\r\n]*|"(?:\\[^]|[^"\\\r\n])*"?/g,
  mixed: /#[^\r\n]*|\/\/[^\r\n]*|\/\*[\s\S]*?(?:\*\/|$)|'(?:\\[^]|[^'\\\r\n])*'?|"(?:\\[^]|[^"\\\r\n])*"?/g
}

// One superset rather than a set per language: the only job here is to keep
// control flow and reserved words out of the "followed by (" rule. Builtins
// (`print`, `range`, `self`, `super`, `object`) are deliberately absent — they
// are painted by the profile's builtin list or the `self`/`this` rule instead.
const KEYWORDS = new Set(`
  if else elif elseif then fi for while until do done switch case default return break continue
  try catch except finally throw throws raise with as from import export use await async
  yield lambda pass assert del global nonlocal in is not and or
  class def struct enum interface trait impl fn func function fun sub proc typename namespace
  module package record union let const var static readonly final abstract virtual override
  public private protected internal sealed extends implements instanceof new delete typeof sizeof
  null nil true false True False None that ref mut move where local
  pub unsafe extern crate dyn match loop go defer chan select goto fallthrough
`.trim().split(/\s+/))

// Declaration shapes, all anchored to the line head. Two forms because the
// generic one ("identifier before a paren") is what catches `return len (x)`
// and `for i in range(n)` as definitions — a keyword-led form and a type-led
// form stay precise, and the call rule still colors whatever they miss.
/** A head is either bare or wrapped in the opening paren of a lisp form. */
const HEAD = '^[\\s(]*'
const MODIFIERS =
  '(?:pub\\s+|static\\s+|inline\\s+|virtual\\s+|extern\\s+|explicit\\s+|constexpr\\s+|async\\s+|export\\s+|default\\s+|public\\s+|private\\s+|protected\\s+|internal\\s+|final\\s+|abstract\\s+|override\\s+|sealed\\s+|open\\s+|partial\\s+|unsafe\\s+)*'
/** `def foo(` / `fn foo(` / `func (r T) foo(` / `(defn foo` — the name is captured. */
const KEYWORD_DECLARATION = new RegExp(
  `${HEAD}${MODIFIERS}(?:def|defn|defmacro|defun|defmethod|fn|func|function|fun|proc|sub|rpc)\\s+(?:\\([^)]*\\)\\s*)?([A-Za-z_]\\w*)`
)
/** `class Foo` / `struct Bar` / `message Baz` — the name never takes a `(`. */
const TYPE_DECLARATION = new RegExp(
  `${HEAD}${MODIFIERS}(?:class|struct|enum|interface|trait|type|record|union|impl|message|service|protocol)\\s+([A-Za-z_]\\w*)`
)
/** `int main(int argc)` / `public static void main(` — a type-ish prefix. */
const TYPE_LED_DECLARATION = /^(\s*[A-Za-z_][\w:<>*&\s]*?\s+)([A-Za-z_]\w*)\s*\(/
/** `package main` / `mod foo` / `import os` / `use std` — a module, never a call. */
const NAMESPACE_DECLARATION = new RegExp(
  `${HEAD}(?:package|namespace|module|mod|defmodule|using|use|import|from)\\s+([A-Za-z_][\\w.]*)`
)
/** `const f = (x) => x` — a bound function, which the call rule cannot see. */
const ARROW_BINDING = new RegExp(
  `${HEAD}(?:let|const|var|val|final)\\s+([A-Za-z_]\\w*)\\s*=\\s*(?:async\\s+)?(?:\\([^)]*\\)\\s*=>|function\\b|[A-Za-z_]\\w*\\s*=>)`
)

/**
 * True when the words before a declaration's name read as a type rather than an
 * expression: `void`, `Task<int>`, `MyClass::`, `char *`, `const std::string&`.
 */
function looksLikeTypePrefix(prefix: string): boolean {
  const word = prefix.trim().split(/\s+/).pop() ?? ''
  if (/^[A-Z]/.test(word)) return true
  if (/[<*&:]/.test(word)) return true
  return TYPE_WORDS.has(word.toLowerCase().replace(/[^a-z0-9_]/g, ''))
}

// ponytail: cap the scan length. Beyond this Monaco's own tokenizer is the only
// color; raise it if a real file needs name-level colors that far down.
const MAX_SCAN_LINES = 5000

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

/** Classify one identifier on one (already masked) line. */
function classify(
  name: string,
  start: number,
  before: string,
  after: string,
  typeDeclarationStart: number | undefined,
  declarationStart: number | undefined,
  namespaceStart: number | undefined,
  params: readonly [number, number] | undefined,
  profile: LanguageProfile
): [number, number] | null {
  if (KEYWORDS.has(name)) return null
  if (start === typeDeclarationStart) return [TT.class, TM.declaration]
  if (start === declarationStart) return [TT.function, TM.declaration]
  if (start === namespaceStart) return [TT.namespace, 0]
  if (profile.annotations && before.endsWith('@')) return [TT.decorator, 0]
  // Shape before position: `MAX_ITEMS` and `SessionState` read the same inside a
  // signature as anywhere else, and a type or constant outranks a parameter name.
  if (/^[A-Z][A-Z0-9_]+$/.test(name)) return [TT.member, TM.readonly]
  if (/^[A-Z][a-zA-Z0-9_]*$/.test(name)) return [TT.class, 0]
  if (profile.types?.has(name)) return [TT.class, 0]
  if (profile.builtins?.has(name) && !before.endsWith('.')) return [TT.macro, TM.defaultLibrary]
  if (profile.bangMacros && /^\s*!/.test(after)) return [TT.macro, TM.defaultLibrary]
  // `self`/`this` outrank the signature they sit in: they are the language's
  // own words, not user-chosen parameters.
  if (name === 'self' || name === 'this') return [TT.member, TM.readonly]
  if (params && start > params[0] && start < params[1]) return [TT.parameter, 0]
  // A name bound by `=` inside an open paren is a keyword argument;
  // outside one it is an assignment and stays ink.
  if (before.lastIndexOf('(') > before.lastIndexOf(')') && /^\s*=(?!=)/.test(after)) {
    return [TT.parameter, 0]
  }
  if (/^\s*\(/.test(after)) return [TT.function, 0]
  if (/(?:\.|->|::)\s*$/.test(before)) return [TT.member, 0]
  return null
}

export function provideSemanticTokens(
  model: monaco.editor.ITextModel
): monaco.languages.ProviderResult<monaco.languages.SemanticTokens> {
  const profile = LEXICAL_PROFILES[model.getLanguageId()]
  if (!profile) return null

  const data: number[] = []
  let prevLine = 0
  let prevChar = 0

  const lineCount = Math.min(model.getLineCount(), MAX_SCAN_LINES)
  const source = Array.from({ length: lineCount }, (_, i) => model.getLineContent(i + 1)).join('\n')
  const mask = MASK[profile.family]
  const lines = source.replace(mask, (value) => value.replace(/[^\r\n]/g, ' ')).split('\n')
  for (const [lineIdx, text] of lines.entries()) {
    const typeMatch = TYPE_DECLARATION.exec(text)
    const functionMatch = KEYWORD_DECLARATION.exec(text)
    const namespaceMatch = NAMESPACE_DECLARATION.exec(text)
    // The type-led and bound-function forms only mean a signature in a C-like
    // file: `(Foo bar)` in lisp is a call, and `let x = 1` binds nothing.
    const cLike = profile.family === 'slash'
    const typeLedMatch = cLike ? TYPE_LED_DECLARATION.exec(text) : null
    const typeLedName =
      typeLedMatch && looksLikeTypePrefix(typeLedMatch[1]) ? typeLedMatch[2] : undefined
    const bindingMatch = cLike ? ARROW_BINDING.exec(text) : null
    // A capture is the last identifier before the `(` of its own match, so the
    // last occurrence of that text inside the match is its offset on the line.
    const typeDeclarationStart = typeMatch ? typeMatch[0].lastIndexOf(typeMatch[1]) : undefined
    const namespaceStart = namespaceMatch
      ? namespaceMatch[0].lastIndexOf(namespaceMatch[1])
      : undefined
    const declarationMatch = functionMatch ?? typeLedMatch ?? bindingMatch
    const declarationName = functionMatch?.[1] ?? typeLedName ?? bindingMatch?.[1]
    const declarationStart = declarationMatch
      ? declarationMatch[0].lastIndexOf(declarationName!)
      : undefined
    // A declaration's parameter list is everything between the parens that open
    // after the name and the last `)` on the line — true for `def f(x)` and for
    // every C-like signature, and narrower than "inside any paren".
    const open =
      declarationStart === undefined || !declarationName
        ? -1
        : text.indexOf('(', declarationStart + declarationName.length)
    const close = open < 0 ? -1 : text.lastIndexOf(')')
    const params: [number, number] | undefined =
      open >= 0 && close > open ? [open, close] : undefined
    for (const match of text.matchAll(/[A-Za-z_]\w*/g)) {
      const name = match[0]
      const start = match.index!
      const hit = classify(
        name,
        start,
        text.slice(0, start),
        text.slice(start + name.length),
        typeDeclarationStart,
        declarationStart,
        namespaceStart,
        params,
        profile
      )
      if (!hit) continue
      ;[prevLine, prevChar] = encode(
        data, prevLine, prevChar, lineIdx, start, name.length, hit[0], hit[1]
      )
    }
  }

  return { data: new Uint32Array(data) }
}

let registered = false

export function registerLexicalSemanticTokens(): monaco.IDisposable[] {
  if (registered) return []
  registered = true
  return Object.keys(LEXICAL_PROFILES).map((languageId) =>
    monaco.languages.registerDocumentSemanticTokensProvider(languageId, {
      getLegend: () => LEXICAL_SEMANTIC_LEGEND,
      provideDocumentSemanticTokens: (model) => provideSemanticTokens(model),
      releaseDocumentSemanticTokens: () => undefined
    })
  )
}
