import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import cssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker'
import htmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker'
import tsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker'

let configured = false
let themesReady = false

export type WorkspaceMonacoThemeName =
  | 'ds-workspace-dark'
  | 'ds-workspace-light'
  | 'ds-ide-workspace-dark'
  | 'ds-ide-workspace-light'

// Match the shared code renderer's light/dark palette, including quiet gutters.
const lightRules: monaco.editor.ITokenThemeRule[] = [
  { token: '', foreground: '24292E' },
  { token: 'comment', foreground: '6A737D' },
  { token: 'keyword', foreground: 'D73A49' },
  { token: 'string', foreground: '032F62' },
  { token: 'number', foreground: '005CC5' },
  { token: 'type', foreground: '6F42C1' },
  { token: 'type.identifier', foreground: '6F42C1' },
  { token: 'delimiter', foreground: '586069' }
]
const darkRules: monaco.editor.ITokenThemeRule[] = [
  { token: '', foreground: 'C7C7C7' },
  { token: 'comment', foreground: '858585', fontStyle: 'italic' },
  { token: 'keyword', foreground: 'FA423E' },
  { token: 'string', foreground: '40C977' },
  { token: 'number', foreground: '7BBCFF' },
  { token: 'type', foreground: 'AD7BF9' },
  { token: 'type.identifier', foreground: 'AD7BF9' },
  { token: 'delimiter', foreground: 'C7C7C7' }
]
const lightChrome = {
  'editor.foreground': '#24292e',
  'editorLineNumber.foreground': '#8b949e',
  'editorLineNumber.activeForeground': '#57606a',
  'editor.selectionBackground': '#0969da20',
  'editor.lineHighlightBackground': '#00000003',
  'editor.lineHighlightBorder': '#00000000'
}
const darkChrome = {
  'editor.foreground': '#c7c7c7',
  'editorLineNumber.foreground': '#737373',
  'editorLineNumber.activeForeground': '#c7c7c7',
  'editor.selectionBackground': '#339cff30',
  'editor.lineHighlightBackground': '#ffffff04',
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
}
