import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import cssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker'
import htmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker'
import tsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker'
import { registerPythonSemanticTokens } from './monaco-python-semantic-tokens'

let configured = false
let themesReady = false

export type WorkspaceMonacoThemeName =
  | 'ds-workspace-dark'
  | 'ds-workspace-light'
  | 'ds-ide-workspace-dark'
  | 'ds-ide-workspace-light'

// GitHub Primer code palette. Monarch tokens (keyword/string/number/comment/
// type/delimiter) plus the semantic-token types the Python provider emits
// (function/method/macro/decorator/parameter/class) — Monaco matches semantic
// token types against the same `token` field once semanticHighlighting is on.
// Light values are primer-light, dark are primer-dark, so both modes reach the
// same richness codex shows instead of light falling back to near-monochrome.
const lightRules: monaco.editor.ITokenThemeRule[] = [
  { token: '', foreground: '24292f' },
  { token: 'comment', foreground: '6e7781' },
  { token: 'keyword', foreground: 'cf222e' },
  { token: 'string', foreground: '0a3069' },
  { token: 'number', foreground: '0550ae' },
  { token: 'type', foreground: '953800' },
  { token: 'type.identifier', foreground: '953800' },
  { token: 'delimiter', foreground: '24292f' },
  { token: 'tag', foreground: '116329' },
  { token: 'attribute.name', foreground: '0550ae' },
  // semantic tokens (Python provider)
  { token: 'function', foreground: '8250df' },
  { token: 'function.declaration', foreground: '8250df' },
  { token: 'method', foreground: '8250df' },
  { token: 'macro', foreground: '0550ae' },
  { token: 'macro.defaultLibrary', foreground: '0550ae' },
  { token: 'decorator', foreground: '8250df' },
  { token: 'parameter', foreground: '953800' },
  { token: 'variable.readonly', foreground: '0550ae' },
  { token: 'class', foreground: '953800' },
  { token: 'class.declaration', foreground: '953800' }
]
const darkRules: monaco.editor.ITokenThemeRule[] = [
  { token: '', foreground: 'c9d1d9' },
  { token: 'comment', foreground: '8b949e', fontStyle: 'italic' },
  { token: 'keyword', foreground: 'ff7b72' },
  { token: 'string', foreground: 'a5d6ff' },
  { token: 'number', foreground: '79c0ff' },
  { token: 'type', foreground: 'ffa657' },
  { token: 'type.identifier', foreground: 'ffa657' },
  { token: 'delimiter', foreground: 'c9d1d9' },
  { token: 'tag', foreground: '7ee787' },
  { token: 'attribute.name', foreground: '79c0ff' },
  // semantic tokens (Python provider)
  { token: 'function', foreground: 'd2a8ff' },
  { token: 'function.declaration', foreground: 'd2a8ff' },
  { token: 'method', foreground: 'd2a8ff' },
  { token: 'macro', foreground: '79c0ff' },
  { token: 'macro.defaultLibrary', foreground: '79c0ff' },
  { token: 'decorator', foreground: 'd2a8ff' },
  { token: 'parameter', foreground: 'ffa657' },
  { token: 'variable.readonly', foreground: '79c0ff' },
  { token: 'class', foreground: 'ffa657' },
  { token: 'class.declaration', foreground: 'ffa657' }
]
// Primer chrome. Light line numbers were `#8b949e` (a dark-theme value) so they
// washed out on white — now primer-light `#6e7781` with a near-ink active.
// Selection uses solid primer highlights instead of faint translucent blue, and
// the current-line highlight is actually visible (GitHub hover grey / dark row).
const lightChrome = {
  'editor.foreground': '#24292f',
  'editorLineNumber.foreground': '#6e7781',
  'editorLineNumber.activeForeground': '#24292f',
  'editor.selectionBackground': '#ddf4ff',
  'editor.inactiveSelectionBackground': '#ddf4ff80',
  'editor.lineHighlightBackground': '#f6f8fa',
  'editor.lineHighlightBorder': '#00000000'
}
const darkChrome = {
  'editor.foreground': '#c9d1d9',
  'editorLineNumber.foreground': '#6e7681',
  'editorLineNumber.activeForeground': '#c9d1d9',
  'editor.selectionBackground': '#264f78',
  'editor.inactiveSelectionBackground': '#264f7880',
  'editor.lineHighlightBackground': '#161b22',
  'editor.lineHighlightBorder': '#00000000'
}

/**
 * Monaco theme ids for workspace editors.
 * Live colors are pinned by CSS to Appearance tokens
 * (`--ds-bg-sidebar` in chat, `--ds-bg-canvas` in IDE) — these hex values are
 * only fallbacks before the stylesheet override applies.
 */
export function ensureWorkspaceMonacoThemes(): void {
  if (themesReady) return
  themesReady = true
  // Chat-mode right panel / tool editor — overridden to `--ds-bg-sidebar`.
  monaco.editor.defineTheme('ds-workspace-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: darkRules,
    colors: {
      ...darkChrome,
      'editor.background': '#171717',
      'editorGutter.background': '#171717',
      'minimap.background': '#171717'
    }
  })
  monaco.editor.defineTheme('ds-workspace-light', {
    base: 'vs',
    inherit: true,
    rules: lightRules,
    colors: {
      ...lightChrome,
      'editor.background': '#f0f0f0',
      'editorGutter.background': '#f0f0f0',
      'minimap.background': '#f0f0f0'
    }
  })
  // IDE work surface — overridden to `--ds-bg-canvas` (appearance surface).
  monaco.editor.defineTheme('ds-ide-workspace-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: darkRules,
    colors: {
      ...darkChrome,
      'editor.background': '#111111',
      'editorGutter.background': '#111111',
      'minimap.background': '#111111'
    }
  })
  monaco.editor.defineTheme('ds-ide-workspace-light', {
    base: 'vs',
    inherit: true,
    rules: lightRules,
    colors: {
      ...lightChrome,
      'editor.background': '#ffffff',
      'editorGutter.background': '#ffffff',
      'minimap.background': '#ffffff'
    }
  })
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
  registerPythonSemanticTokens()
}
