import { loader } from '@monaco-editor/react'
import * as monaco from 'monaco-editor'
import editorWorker from 'monaco-editor/esm/vs/editor/editor.worker?worker'
import jsonWorker from 'monaco-editor/esm/vs/language/json/json.worker?worker'
import cssWorker from 'monaco-editor/esm/vs/language/css/css.worker?worker'
import htmlWorker from 'monaco-editor/esm/vs/language/html/html.worker?worker'
import tsWorker from 'monaco-editor/esm/vs/language/typescript/ts.worker?worker'

let configured = false

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

export function languageForPath(path: string): string {
  const fileName = path.split(/[/\\]/).pop() ?? path
  const ext = fileName.includes('.') ? fileName.split('.').pop()?.toLowerCase() : ''
  switch (ext) {
    case 'ts':
    case 'tsx':
      return 'typescript'
    case 'js':
    case 'jsx':
    case 'mjs':
    case 'cjs':
      return 'javascript'
    case 'json':
      return 'json'
    case 'md':
    case 'markdown':
      return 'markdown'
    case 'py':
      return 'python'
    case 'css':
      return 'css'
    case 'scss':
      return 'scss'
    case 'less':
      return 'less'
    case 'html':
    case 'htm':
      return 'html'
    case 'yaml':
    case 'yml':
      return 'yaml'
    case 'xml':
      return 'xml'
    case 'sh':
    case 'bash':
      return 'shell'
    case 'go':
      return 'go'
    case 'rs':
      return 'rust'
    case 'toml':
      return 'ini'
    default:
      return 'plaintext'
  }
}
