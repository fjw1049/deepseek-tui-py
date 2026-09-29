/**
 * One palette for every code surface.
 *
 * The workspace editor (Monaco) and the chat / diff / markdown blocks (Shiki)
 * used to carry two unrelated colour sets — GitHub Primer in the editor, Codex
 * in chat — so the same file changed character as it moved between them. Both
 * surfaces now build their themes from here, so a value can only drift once.
 *
 * Slots are semantic ("what a token *is*"), never per-grammar: each surface
 * maps its own scope names onto a slot below.
 */

export type CodeAppearance = 'light' | 'dark'

export type CodeSlot =
  | 'ink'
  | 'comment'
  | 'keyword'
  | 'string'
  | 'number'
  | 'constant'
  | 'function'
  | 'type'
  | 'parameter'
  | 'property'
  | 'macro'
  | 'decorator'
  | 'tag'
  | 'attribute'
  | 'punctuation'
  | 'invalid'
  | 'added'
  | 'removed'
  | 'changed'

export type CodeSlotStyle = {
  color: string
  /** Monaco `fontStyle` / TextMate `fontStyle`, lower-case, space separated. */
  fontStyle?: 'italic' | 'bold' | 'italic bold'
  /** Only the diff slots carry a tint; everywhere else the surface supplies it. */
  background?: string
}

/** `[token, slot]`, or `[token, slot, fontStyle]` where the scope refines it. */
export type ScopeSlot = readonly [string, CodeSlot, CodeSlotStyle['fontStyle']?]

// Both sets are tuned for the same perceived weight, which is not the same as
// the same hue at the same saturation: a dark surface makes a mid-tone glow,
// while white washes saturation out. Primer-light's originals were built for UI
// chrome, not for code, and read flat here — `#0a3069` strings sat a hair
// darker than body ink, and seven slots shared one blue at one lightness. Every
// value below clears 4.5:1 against its own background and keeps the hue role of
// its dark counterpart, so a type stays teal and a string stays green in both.
const LIGHT: Record<CodeSlot, CodeSlotStyle> = {
  ink: { color: '#24292f' },
  comment: { color: '#6e7781', fontStyle: 'italic' },
  keyword: { color: '#cf222e' },
  string: { color: '#0a7a3f' },
  number: { color: '#0b57c2' },
  constant: { color: '#0b57c2' },
  function: { color: '#7b3fd4' },
  type: { color: '#0d7385' },
  parameter: { color: '#a03e00' },
  property: { color: '#0b57c2' },
  macro: { color: '#0b57c2' },
  decorator: { color: '#7b3fd4' },
  tag: { color: '#116329' },
  attribute: { color: '#0969da' },
  punctuation: { color: '#24292f' },
  invalid: { color: '#cf222e' },
  added: { color: '#187935', background: '#dafbe1' },
  removed: { color: '#cf222e', background: '#ffebe9' },
  changed: { color: '#0969da' }
}

// Dark keeps the Codex chat set, with one split: types were the same violet as
// the functions they contain, so a class read as a call. Teal separates them
// and matches the light half.
const DARK: Record<CodeSlot, CodeSlotStyle> = {
  ink: { color: '#ffffff' },
  comment: { color: '#858585', fontStyle: 'italic' },
  keyword: { color: '#fa423e' },
  string: { color: '#40c977' },
  number: { color: '#7bbcff' },
  constant: { color: '#7bbcff' },
  function: { color: '#ad7bf9' },
  type: { color: '#4ec9b0' },
  parameter: { color: '#c7c7c7' },
  property: { color: '#c7c7c7' },
  macro: { color: '#7bbcff' },
  decorator: { color: '#ad7bf9' },
  tag: { color: '#339cff' },
  attribute: { color: '#339cff' },
  punctuation: { color: '#c7c7c7' },
  invalid: { color: '#fa423e' },
  added: { color: '#40c977', background: '#173222' },
  removed: { color: '#fa423e', background: '#351b1b' },
  changed: { color: '#339cff' }
}

export const CODE_PALETTE: Record<CodeAppearance, Record<CodeSlot, CodeSlotStyle>> = {
  light: LIGHT,
  dark: DARK
}

/**
 * Monaco token name → slot. Monaco appends the language to every token
 * (`keyword.go`) and matches by longest dotted prefix, so the bare names below
 * also cover their language-qualified variants (`annotation` catches
 * `annotation.java`, `regexp` catches `regexp.escape.control.js`).
 *
 * `operator` is deliberately absent: VS Code leaves operators at ink weight.
 */
export const MONACO_SCOPE_SLOTS: ReadonlyArray<ScopeSlot> = [
  ['', 'ink'],
  ['comment', 'comment'],
  ['metatag', 'comment'],
  ['keyword', 'keyword'],
  ['string', 'string'],
  ['regexp', 'string'],
  ['number', 'number'],
  ['constant', 'constant'],
  ['variable.readonly', 'constant'],
  ['type', 'type'],
  ['type.identifier', 'type'],
  ['class', 'type'],
  ['class.declaration', 'type'],
  ['interface', 'type'],
  ['enum', 'type'],
  ['struct', 'type'],
  ['namespace', 'type'],
  ['typeParameter', 'type'],
  ['function', 'function'],
  ['function.declaration', 'function'],
  ['method', 'function'],
  ['macro', 'macro'],
  ['macro.defaultLibrary', 'macro'],
  ['predefined', 'macro'],
  ['keyword.directive', 'macro'],
  ['decorator', 'decorator'],
  ['annotation', 'decorator'],
  ['parameter', 'parameter'],
  ['variable', 'attribute'],
  ['tag', 'tag'],
  ['attribute.name', 'attribute'],
  ['key', 'attribute'],
  ['attribute.value', 'string'],
  ['delimiter', 'punctuation'],
  ['punctuation', 'punctuation'],
  ['strong', 'ink', 'bold'],
  ['emphasis', 'ink', 'italic'],
  ['invalid', 'invalid']
]

/**
 * TextMate scope → slot, for the Shiki themes behind chat / diff / markdown.
 * TextMate has no single "type" scope, so the Codex set's own aliases stay.
 */
export const SHIKI_SCOPE_SLOTS: ReadonlyArray<ScopeSlot> = [
  ['comment', 'comment'],
  ['punctuation.definition.comment', 'comment'],
  ['string.comment', 'comment'],
  ['keyword', 'keyword'],
  ['storage', 'keyword'],
  ['storage.type', 'keyword'],
  ['storage.modifier', 'keyword'],
  ['string', 'string'],
  ['punctuation.definition.string', 'string'],
  ['constant', 'constant'],
  ['constant.numeric', 'constant'],
  ['variable.language', 'constant'],
  ['support.constant', 'constant'],
  ['entity.name.function', 'function'],
  ['support.function', 'function'],
  ['meta.function-call', 'function'],
  ['entity.name.type', 'type'],
  ['entity.other.inherited-class', 'type'],
  ['entity.name.namespace', 'type'],
  ['support.class', 'type'],
  ['support.type', 'type'],
  ['variable.parameter', 'parameter'],
  ['variable.other', 'property'],
  ['meta.property-name', 'property'],
  ['support.type.property-name', 'property'],
  ['meta.object-literal.key', 'property'],
  ['entity.name.tag', 'tag'],
  ['entity.other.attribute-name', 'attribute'],
  ['punctuation', 'punctuation'],
  ['meta.brace', 'punctuation'],
  ['markup.inserted', 'added'],
  ['meta.diff.header.to-file', 'added'],
  ['punctuation.definition.inserted', 'added'],
  ['markup.deleted', 'removed'],
  ['meta.diff.header.from-file', 'removed'],
  ['punctuation.definition.deleted', 'removed'],
  ['markup.changed', 'changed'],
  ['punctuation.definition.changed', 'changed'],
  ['meta.diff.range', 'changed'],
  ['markup.bold', 'ink', 'bold'],
  ['markup.italic', 'ink', 'italic'],
  ['invalid', 'invalid']
]

/**
 * `editor.*` colors shared by Monaco and Shiki (both accept this key set).
 * Monaco-only keys — line numbers, minimap, per-theme background — stay with
 * the Monaco themes; per-surface background stays with each surface.
 */
export const CODE_CHROME: Record<CodeAppearance, Record<string, string>> = {
  light: {
    'editor.foreground': LIGHT.ink.color,
    'editor.selectionBackground': '#ddf4ff',
    'editor.inactiveSelectionBackground': '#ddf4ff80',
    'editor.lineHighlightBackground': '#f6f8fa',
    'editorCursor.foreground': '#24292f',
    'editorGutter.addedBackground': LIGHT.added.color,
    'editorGutter.deletedBackground': LIGHT.removed.color,
    'editorGutter.modifiedBackground': LIGHT.changed.color,
    'diffEditor.insertedTextBackground': '#1a7f3724',
    'diffEditor.removedTextBackground': '#cf222e24'
  },
  dark: {
    'editor.foreground': DARK.ink.color,
    'editor.selectionBackground': '#339cff44',
    'editor.inactiveSelectionBackground': '#339cff22',
    'editor.lineHighlightBackground': '#ffffff08',
    'editorCursor.foreground': '#ffffff',
    'editorGutter.addedBackground': DARK.added.color,
    'editorGutter.deletedBackground': DARK.removed.color,
    'editorGutter.modifiedBackground': DARK.changed.color,
    'diffEditor.insertedTextBackground': '#40c97724',
    'diffEditor.removedTextBackground': '#fa423e24'
  }
}
