import { highlightCodeHtml } from './highlight-code'
self.onmessage = async (event: MessageEvent<{ id: number; code: string; language: string }>) => {
  const { id, code, language } = event.data
  try { self.postMessage({ id, html: await highlightCodeHtml(code, language) }) }
  catch { self.postMessage({ id, error: true }) }
}
