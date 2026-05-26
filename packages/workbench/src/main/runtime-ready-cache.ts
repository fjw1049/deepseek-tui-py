// Hot-path cache for ensureRuntime. A single user message triggers ~5–7 IPC
// calls; each one used to run waitForRuntimeHealth + probeThreadApi (2 HTTPs).
// After a full validation succeeds, skip both probes for a short window.
// The cache is invalidated on settings changes, runtime restart, and any
// caller-observed transport failure (401/408/503) so a broken runtime is
// detected on the very next call.

export type RuntimeReadyCache = {
  markReady: () => void
  invalidate: (reason: string) => void
  isFresh: () => boolean
}

export type RuntimeReadyCacheOptions = {
  ttlMs?: number
  now?: () => number
  onTrace?: (event: 'hit' | 'miss' | 'invalidate', reason?: string) => void
}

export const DEFAULT_RUNTIME_READY_TTL_MS = 5_000

export function createRuntimeReadyCache(options: RuntimeReadyCacheOptions = {}): RuntimeReadyCache {
  const ttl = options.ttlMs ?? DEFAULT_RUNTIME_READY_TTL_MS
  const now = options.now ?? Date.now
  const trace = options.onTrace
  let validUntil = 0

  return {
    markReady(): void {
      validUntil = now() + ttl
    },
    invalidate(reason: string): void {
      if (validUntil !== 0) trace?.('invalidate', reason)
      validUntil = 0
    },
    isFresh(): boolean {
      const fresh = validUntil > now()
      trace?.(fresh ? 'hit' : 'miss')
      return fresh
    }
  }
}
