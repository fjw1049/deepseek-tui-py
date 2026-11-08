import { provideSemanticTokens } from './lexical-semantic-scan'
import type { editor } from 'monaco-editor'

self.onmessage = (event: MessageEvent<{ source: string; language: string }>) => {
  const lines = event.data.source.split('\n')
  const model = {
    getLanguageId: () => event.data.language,
    getLineCount: () => lines.length,
    getLineContent: (line: number) => lines[line - 1]
  } as editor.ITextModel
  const result = provideSemanticTokens(model) as { data: Uint32Array } | null
  const data = result?.data ?? new Uint32Array()
  self.postMessage(data, { transfer: [data.buffer] })
}
