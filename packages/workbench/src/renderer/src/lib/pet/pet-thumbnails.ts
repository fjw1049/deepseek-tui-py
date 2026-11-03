import { useEffect, useState } from 'react'

// Successful thumbnails are reused throughout the session; failures can be retried.
const cache = new Map<string, string>()
const pending = new Set<string>()
const queue: string[] = []
const listeners = new Set<() => void>()
let active = 0

export function preloadPetThumbnails(slugs: string[]): void {
  const resolve = window.dsGui?.resolvePetThumbnails
  if (!resolve) return
  for (const slug of slugs) {
    if (cache.has(slug) || pending.has(slug)) continue
    pending.add(slug)
    queue.push(slug)
  }
  const pump = (): void => {
    while (active < 6 && queue.length) {
      const slug = queue.shift()!
      active++
      // Resolve separately so a slow image cannot hold back ready thumbnails.
      void Promise.resolve().then(() => resolve([slug])).then(result => {
        if (result[slug]) cache.set(slug, result[slug]!)
      }).catch(() => {
        // A later settings visit or refresh may retry.
      }).finally(() => {
        pending.delete(slug)
        active--
        listeners.forEach(listener => listener())
        pump()
      })
    }
  }
  pump()
}

export function usePetThumbnails(slugs: string[]): Record<string, string | undefined> {
  const [, setVersion] = useState(0)
  useEffect(() => {
    const update = (): void => setVersion(version => version + 1)
    listeners.add(update)
    preloadPetThumbnails(slugs)
    return () => { listeners.delete(update) }
  }, [slugs])
  return Object.fromEntries(slugs.map(slug => [slug, cache.get(slug)]))
}
