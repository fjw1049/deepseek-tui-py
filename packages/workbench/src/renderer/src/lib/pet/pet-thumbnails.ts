import { useEffect, useState } from 'react'

// Thumbnails are tiny and never change for a slug, so one cache serves the session.
const cache = new Map<string, string | null>()
const inflight = new Set<string>()

export function usePetThumbnails(slugs: string[]): Record<string, string | null | undefined> {
  const [, setVersion] = useState(0)

  useEffect(() => {
    const resolve = window.dsGui?.resolvePetThumbnails
    const missing = slugs.filter((slug) => !cache.has(slug) && !inflight.has(slug))
    if (!resolve || missing.length === 0) return
    let cancelled = false
    missing.forEach((slug) => inflight.add(slug))
    void resolve(missing).then((result) => {
      for (const slug of missing) cache.set(slug, result[slug] ?? null)
    }, () => {
      // Leave them uncached so a later render can retry.
    }).finally(() => {
      missing.forEach((slug) => inflight.delete(slug))
      if (!cancelled) setVersion((version) => version + 1)
    })
    return () => { cancelled = true }
  }, [slugs])

  return Object.fromEntries(slugs.map((slug) => [slug, cache.get(slug)]))
}
