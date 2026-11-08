import * as monaco from 'monaco-editor'
import SemanticWorker from './semantic-tokens.worker?worker'
import { LEXICAL_PROFILES, LEXICAL_SEMANTIC_LEGEND } from './lexical-semantic-scan'
export { LEXICAL_PROFILES, LEXICAL_SEMANTIC_LEGEND, provideSemanticTokens } from './lexical-semantic-scan'

type Result = { data: Uint32Array }
type Entry = { version: number; language: string; result?: Result; promise: Promise<Result | null>; cancel: () => void }
const entries = new WeakMap<monaco.editor.ITextModel, Entry>()
const workers = new WeakMap<monaco.editor.ITextModel, { worker: Worker; stop: () => void; idle?: ReturnType<typeof setTimeout> }>()
function acquireWorker(model: monaco.editor.ITextModel) {
  const existing = workers.get(model)
  if (existing) { clearTimeout(existing.idle); return existing }
  const worker = new SemanticWorker()
  const stop = () => {
    clearTimeout(state.idle)
    worker.terminate()
    workers.delete(model)
    dispose.dispose()
    detach.dispose()
  }
  const state: { worker: Worker; stop: () => void; idle?: ReturnType<typeof setTimeout> } = { worker, stop }
  const dispose = model.onWillDispose(stop)
  const detach = model.onDidChangeAttached(() => { if (!model.isAttachedToEditor()) stop() })
  workers.set(model, state)
  return state
}


/** First paint and Monaco's provider share the same versioned background result. */
export function prepareSemanticTokens(model: monaco.editor.ITextModel): Promise<Result | null> {
  if (model.isDisposed() || !LEXICAL_PROFILES[model.getLanguageId()]) return Promise.resolve(null)
  const version = model.getVersionId()
  const language = model.getLanguageId()
  const existing = entries.get(model)
  if (existing?.version === version && existing.language === language) return existing.promise
  existing?.cancel()
  let cancel = () => {}
  const entry: Entry = {
    version, language,
    promise: new Promise(resolve => {
      const state = acquireWorker(model)
      const worker = state.worker
      let done = false
      const finish = (data?: Uint32Array) => {
        if (done) return
        done = true
        worker.onmessage = null
        worker.onerror = null
        if (data) state.idle = setTimeout(state.stop, 30_000)
        else state.stop()
        disposal.dispose()
        detach.dispose()
        const result = data && !model.isDisposed() && model.getVersionId() === version && model.getLanguageId() === language ? { data } : null
        if (!result) entries.delete(model)
        else entry.result = result
        resolve(result)
      }
      cancel = () => finish()
      const disposal = model.onWillDispose(cancel)
      const detach = model.onDidChangeAttached(() => { if (!model.isAttachedToEditor()) cancel() })
      worker.onmessage = (event: MessageEvent<Uint32Array>) => finish(event.data)
      worker.onerror = () => finish()
      worker.postMessage({ source: model.getValue(), language })
    }),
    cancel: () => cancel()
  }
  entries.set(model, entry)
  return entry.promise
}

export function cancelSemanticPreparation(model: monaco.editor.ITextModel): void {
  entries.get(model)?.cancel()
}

let registered = false
export function registerLexicalSemanticTokens(): monaco.IDisposable[] {
  if (registered) return []
  registered = true
  return Object.keys(LEXICAL_PROFILES).map(languageId =>
    monaco.languages.registerDocumentSemanticTokensProvider(languageId, {
      getLegend: () => LEXICAL_SEMANTIC_LEGEND,
      provideDocumentSemanticTokens(model, _lastResultId, token) {
        if (token.isCancellationRequested) return null
        const existing = entries.get(model)
        if (existing?.version === model.getVersionId() && existing.language === model.getLanguageId() && existing.result) return existing.result
        const promise = prepareSemanticTokens(model)
        const request = entries.get(model)
        const cancellation = token.onCancellationRequested(() => request?.cancel())
        return promise.finally(() => cancellation.dispose())
      },
      releaseDocumentSemanticTokens: () => undefined
    })
  )
}
