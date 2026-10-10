import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import cssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker'
import htmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker'
import tsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker'
import { CODE_CHROME, CODE_PALETTE, MONACO_SCOPE_SLOTS, type CodeAppearance } from './code-palette'
import { registerLexicalSemanticTokens } from './monaco-lexical-semantic-tokens'
import { buildChromeThemeCssVars } from '@shared/appearance-derive'
import { getAppearanceSettings } from './apply-appearance'

let configured = false
let lastThemeKey = ''

export type WorkspaceMonacoThemeName =
  | 'ds-workspace-dark'
  | 'ds-workspace-light'
  | 'ds-ide-workspace-dark'
  | 'ds-ide-workspace-light'

// One palette for both surfaces: lib/code-palette.ts holds the slots, this file
// only maps them onto Monaco token names. Monarch tokens (keyword/string/
// number/comment/type/delimiter) and the semantic-token types the lexical
// provider emits (function/method/macro/decorator/parameter/class) both match
// the same `token` field once semanticHighlighting is on. Monaco appends the
// language to a token (`keyword.go`) and matches the longest dotted prefix, so
// one rule per scope covers every language that emits it.
export function themeRules(appearance: CodeAppearance): monaco.editor.ITokenThemeRule[] {
  const slots = CODE_PALETTE[appearance]
  return MONACO_SCOPE_SLOTS.map(([token, slot, fontStyle]) => {
    const style = slots[slot]
    const rule: monaco.editor.ITokenThemeRule = { token, foreground: style.color.slice(1) }
    const font = fontStyle ?? style.fontStyle
    if (font) rule.fontStyle = font
    return rule
  })
}
/** Refresh Monaco's own selection, gutter, minimap and diff colors on palette edits. */
export function ensureWorkspaceMonacoThemes(): void {
  const { themes } = getAppearanceSettings()
  const key = JSON.stringify(themes)
  if (key === lastThemeKey) return
  lastThemeKey = key

  for (const variant of ['light', 'dark'] as const) {
    const theme = themes[variant]
    const vars = buildChromeThemeCssVars(theme, variant)
    const accent = vars['--ds-accent']
    const chrome = {
      ...CODE_CHROME[variant],
      'editor.foreground': theme.ink,
      'editorCursor.foreground': theme.ink,
      'editor.selectionBackground': `${accent}${variant === 'light' ? '2e' : '3d'}`,
      'editor.inactiveSelectionBackground': `${accent}20`,
      'editor.lineHighlightBackground': `${theme.ink}08`,
      'editor.lineHighlightBorder': '#00000000',
      'editorLineNumber.foreground': `${theme.ink}99`,
      'editorLineNumber.activeForeground': theme.ink,
      'editorGutter.addedBackground': theme.semanticColors.diffAdded,
      'editorGutter.deletedBackground': theme.semanticColors.diffRemoved,
      'editorGutter.modifiedBackground': accent,
      'diffEditor.insertedTextBackground': `${theme.semanticColors.diffAdded}24`,
      'diffEditor.removedTextBackground': `${theme.semanticColors.diffRemoved}24`
    }
    const rules = themeRules(variant).map((rule) =>
      rule.token === '' ? { ...rule, foreground: theme.ink.slice(1) } : rule
    )
    for (const ideCanvas of [false, true]) {
      const background = vars[ideCanvas ? '--bg-canvas' : '--bg-sidebar']
      monaco.editor.defineTheme(`ds-${ideCanvas ? 'ide-' : ''}workspace-${variant}`, {
        base: variant === 'dark' ? 'vs-dark' : 'vs',
        inherit: true,
        rules,
        colors: {
          ...chrome,
          'editor.background': background,
          'editorGutter.background': background,
          'minimap.background': background
        }
      })
    }
  }
}

export function workspaceMonacoTheme(ideCanvas = false): WorkspaceMonacoThemeName {
  ensureWorkspaceMonacoThemes()
  const dark = document.documentElement.getAttribute('data-theme') === 'dark'
  if (ideCanvas) {
    return dark ? 'ds-ide-workspace-dark' : 'ds-ide-workspace-light'
  }
  return dark ? 'ds-workspace-dark' : 'ds-workspace-light'
}

export function ensureMonacoConfigured(): void {
  if (configured) return
  configured = true

  self.MonacoEnvironment = {
    getWorker(_, label) {
      if (label === 'json') return new jsonWorker()
      if (label === 'css' || label === 'scss' || label === 'less') return new cssWorker()
      if (label === 'html' || label === 'handlebars' || label === 'razor') return new htmlWorker()
      if (label === 'typescript' || label === 'javascript') return new tsWorker()
      return new editorWorker()
    }
  }

  loader.config({ monaco })
  registerLexicalSemanticTokens()
}
