import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import cssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker'
import htmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker'
import tsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker'

let configured = false
let themesReady = false

/** Match Monaco canvas to `--bg-sidebar` tokens in index.css (both themes at once). */
export function ensureWorkspaceMonacoThemes(): void {
  if (themesReady) return
  themesReady = true
  monaco.editor.defineTheme('ds-workspace-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [],
    colors: {
      'editor.background': '#171717',
      'editorGutter.background': '#171717',
      'minimap.background': '#171717'
    }
  })
  monaco.editor.defineTheme('ds-workspace-light', {
    base: 'vs',
    inherit: true,
    rules: [],
    colors: {
      'editor.background': '#f0f0f0',
      'editorGutter.background': '#f0f0f0',
      'minimap.background': '#f0f0f0'
    }
  })
}

export function workspaceMonacoTheme(): 'ds-workspace-dark' | 'ds-workspace-light' {
  ensureWorkspaceMonacoThemes()
  return document.documentElement.getAttribute('data-theme') === 'dark'
    ? 'ds-workspace-dark'
    : 'ds-workspace-light'
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
