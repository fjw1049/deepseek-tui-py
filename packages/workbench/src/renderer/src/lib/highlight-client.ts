import HighlightWorker from './highlight.worker?worker'
import { normalizeLanguage } from '../components/chat/code-language'
import { renderFallbackHtml } from './code-fallback'

type Consumer = { resolve: (html: string) => void; reject: (error: Error) => void; cleanup: () => void }
type Job = { id: number; key: string; code: string; language: string; consumers: Set<Consumer> }
let worker: Worker | undefined
let nextId = 0
let active: Job | undefined
let idleTimer: ReturnType<typeof setTimeout> | undefined
const jobs = new Map<string, Job>()
const cache = new Map<string, string>()
let cacheSize = 0
const MAX_CACHE_SIZE = 4_000_000

function pump(): void {
  if (active) return
  clearTimeout(idleTimer)
  const job = jobs.values().next().value as Job | undefined
  if (!job) {
    idleTimer = setTimeout(() => { worker?.terminate(); worker = undefined }, 30_000)
    return
  }
  active = job
  try {
    worker ??= new HighlightWorker()
    worker.onmessage = event => {
      if (event.data.id !== active?.id) return
      finish(event.data.error ? undefined : event.data.html)
    }
    worker.onerror = () => { worker?.terminate(); worker = undefined; finish() }
    worker.postMessage({ id: job.id, code: job.code, language: job.language })
  } catch { finish() }
}

function finish(html?: string): void {
  const job = active
  if (!job) return
  active = undefined
  jobs.delete(job.key)
  if (html !== undefined && job.key.length + html.length <= MAX_CACHE_SIZE) {
    cache.set(job.key, html)
    cacheSize += job.key.length + html.length
    while (cacheSize > MAX_CACHE_SIZE) {
      const oldest = cache.keys().next().value!
      cacheSize -= oldest.length + cache.get(oldest)!.length
      cache.delete(oldest)
    }
  }
  for (const consumer of job.consumers) {
    consumer.cleanup()
    if (html === undefined) consumer.reject(new Error('Highlight worker failed'))
    else consumer.resolve(html)
  }
  pump()
}

export function highlightCodeHtml(code: string, language: string, signal?: AbortSignal): Promise<string> {
  if (signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'))
  if (!normalizeLanguage(language)) return Promise.resolve(renderFallbackHtml(code))
  const key = language + '\0' + code
  const cached = cache.get(key)
  if (cached !== undefined) return Promise.resolve(cached)
  let job = jobs.get(key)
  if (!job) {
    job = { id: ++nextId, key, code, language, consumers: new Set() }
    jobs.set(key, job)
  }
  const request = job
  return new Promise<string>((resolve, reject) => {
    const abort = () => {
      request.consumers.delete(consumer)
      consumer.cleanup()
      reject(new DOMException('Aborted', 'AbortError'))
      if (!request.consumers.size) {
        jobs.delete(key)
        if (active === request) {
          worker?.terminate()
          worker = undefined
          active = undefined
        }
        pump()
      }
    }
    const consumer: Consumer = { resolve, reject, cleanup: () => signal?.removeEventListener('abort', abort) }
    request.consumers.add(consumer)
    signal?.addEventListener('abort', abort, { once: true })
    pump()
  })
}
