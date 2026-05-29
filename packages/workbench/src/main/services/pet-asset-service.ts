import { app } from 'electron'
import { createHash } from 'node:crypto'
import { access, mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

import type {
  PetFeaturedCacheResult,
  PetManifestFetchResult,
  PetManifestEntry,
  PetManifestSlim,
  PetSpritesheetResolveResult
} from '../../shared/pet-manifest'
import { DEFAULT_PET_SLUG, PETDEX_MANIFEST_URL } from '../../shared/pet-manifest'
import { isAllowedManifestUrl, isAllowedSpritesheetUrl } from '../../shared/pet-url-allowlist'

const MANIFEST_TTL_MS = 5 * 60 * 1000
const FETCH_TIMEOUT_MS = 20_000
const PET_SLUG_PATTERN = /^[a-z0-9][a-z0-9_-]{0,79}$/i

type ManifestCacheRecord = {
  fetchedAt: number
  manifest: PetManifestSlim
}

let memoryManifest: ManifestCacheRecord | null = null

function cacheRoot(): string {
  return join(app.getPath('userData'), 'pet-cache')
}

function manifestCachePath(): string {
  return join(cacheRoot(), 'manifest.json')
}

function spritesheetCachePath(slug: string): string {
  return join(cacheRoot(), `${slug}.webp`)
}

function normalizePetSlug(value: string | undefined, fallback = DEFAULT_PET_SLUG): string {
  const slug = (value?.trim() || fallback).slice(0, 80)
  return PET_SLUG_PATTERN.test(slug) ? slug : fallback
}

async function ensureCacheDir(): Promise<void> {
  await mkdir(cacheRoot(), { recursive: true })
}

async function readManifestCacheFile(): Promise<ManifestCacheRecord | null> {
  try {
    const raw = await readFile(manifestCachePath(), 'utf8')
    const parsed = JSON.parse(raw) as ManifestCacheRecord
    if (!parsed?.manifest?.pets || typeof parsed.fetchedAt !== 'number') return null
    return parsed
  } catch {
    return null
  }
}

async function writeManifestCacheFile(record: ManifestCacheRecord): Promise<void> {
  await ensureCacheDir()
  await writeFile(manifestCachePath(), JSON.stringify(record), 'utf8')
}

function parseManifestBody(body: unknown): PetManifestSlim | null {
  if (!body || typeof body !== 'object') return null
  const row = body as Record<string, unknown>
  if (!Array.isArray(row.pets)) return null
  const pets = row.pets
    .map((pet) => {
      if (!pet || typeof pet !== 'object') return null
      const item = pet as Record<string, unknown>
      const rawSlug = typeof item.slug === 'string' ? item.slug.trim() : ''
      const slug = PET_SLUG_PATTERN.test(rawSlug) ? rawSlug : ''
      const displayName = typeof item.displayName === 'string' ? item.displayName.trim() : ''
      const spritesheetUrl =
        typeof item.spritesheetUrl === 'string' ? item.spritesheetUrl.trim() : ''
      if (!slug || !displayName || !spritesheetUrl) return null
      if (!isAllowedSpritesheetUrl(spritesheetUrl)) return null
      return {
        slug,
        displayName,
        kind: typeof item.kind === 'string' ? item.kind : 'creature',
        submittedBy:
          typeof item.submittedBy === 'string' && item.submittedBy.trim()
            ? item.submittedBy.trim()
            : null,
        spritesheetUrl,
        petJsonUrl: typeof item.petJsonUrl === 'string' ? item.petJsonUrl : '',
        zipUrl: typeof item.zipUrl === 'string' ? item.zipUrl : null
      }
    })
    .filter((pet): pet is NonNullable<typeof pet> => pet != null)

  return {
    generatedAt: typeof row.generatedAt === 'string' ? row.generatedAt : new Date().toISOString(),
    total: typeof row.total === 'number' ? row.total : pets.length,
    pets
  }
}

async function fetchManifestRemote(): Promise<PetManifestSlim> {
  if (!isAllowedManifestUrl(PETDEX_MANIFEST_URL)) {
    throw new Error('Manifest URL is not allowlisted.')
  }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
  try {
    const response = await fetch(PETDEX_MANIFEST_URL, {
      signal: controller.signal,
      headers: { Accept: 'application/json' }
    })
    if (!response.ok) {
      throw new Error(`Manifest request failed (${response.status}).`)
    }
    const body = (await response.json()) as unknown
    const manifest = parseManifestBody(body)
    if (!manifest || manifest.pets.length === 0) {
      throw new Error('Manifest response was empty or invalid.')
    }
    return manifest
  } finally {
    clearTimeout(timer)
  }
}

export async function fetchPetManifest(force = false): Promise<PetManifestFetchResult> {
  const now = Date.now()
  if (!force && memoryManifest && now - memoryManifest.fetchedAt < MANIFEST_TTL_MS) {
    return { ok: true, manifest: memoryManifest.manifest, cached: true }
  }

  const disk = await readManifestCacheFile()
  if (!force && disk && now - disk.fetchedAt < MANIFEST_TTL_MS) {
    memoryManifest = disk
    return { ok: true, manifest: disk.manifest, cached: true }
  }

  try {
    const manifest = await fetchManifestRemote()
    const record = { fetchedAt: now, manifest }
    memoryManifest = record
    await writeManifestCacheFile(record)
    return { ok: true, manifest, cached: false }
  } catch (error) {
    if (disk) {
      memoryManifest = disk
      return { ok: true, manifest: disk.manifest, cached: true }
    }
    return {
      ok: false,
      message: error instanceof Error ? error.message : String(error)
    }
  }
}

async function downloadSpritesheet(url: string, slug: string): Promise<void> {
  if (!isAllowedSpritesheetUrl(url)) {
    throw new Error('Spritesheet URL is not allowlisted.')
  }
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
  try {
    const response = await fetch(url, { signal: controller.signal })
    if (!response.ok) {
      throw new Error(`Spritesheet request failed (${response.status}).`)
    }
    const buffer = Buffer.from(await response.arrayBuffer())
    if (buffer.length < 256) {
      throw new Error('Spritesheet payload was too small.')
    }
    await ensureCacheDir()
    await writeFile(spritesheetCachePath(slug), buffer)
  } finally {
    clearTimeout(timer)
  }
}

function spritesheetUrlHash(url: string): string {
  return createHash('sha256').update(url).digest('hex').slice(0, 16)
}

async function readCachedSpritesheet(slug: string): Promise<Buffer | null> {
  try {
    await access(spritesheetCachePath(slug))
    return await readFile(spritesheetCachePath(slug))
  } catch {
    return null
  }
}

async function isSpritesheetCacheFresh(entry: PetManifestEntry): Promise<boolean> {
  const urlHash = spritesheetUrlHash(entry.spritesheetUrl)
  const metaPath = join(cacheRoot(), `${entry.slug}.meta`)
  try {
    const cached = await readCachedSpritesheet(entry.slug)
    if (!cached) return false
    const metaRaw = await readFile(metaPath, 'utf8')
    return metaRaw.trim() === urlHash
  } catch {
    return false
  }
}

async function ensureSpritesheetCached(entry: PetManifestEntry): Promise<boolean> {
  const urlHash = spritesheetUrlHash(entry.spritesheetUrl)
  const metaPath = join(cacheRoot(), `${entry.slug}.meta`)
  if (!(await isSpritesheetCacheFresh(entry))) {
    await downloadSpritesheet(entry.spritesheetUrl, entry.slug)
    await ensureCacheDir()
    await writeFile(metaPath, urlHash, 'utf8')
  }
  return true
}

export async function cacheFeaturedPets(limit = 15): Promise<PetFeaturedCacheResult> {
  const boundedLimit = Math.min(15, Math.max(1, Math.floor(limit)))
  const manifestResult = await fetchPetManifest()
  if (!manifestResult.ok) {
    return { ok: false, message: manifestResult.message }
  }
  const pets = manifestResult.manifest.pets.slice(0, boundedLimit)
  const cachedSlugs: string[] = []
  for (const pet of pets) {
    if (await isSpritesheetCacheFresh(pet)) {
      cachedSlugs.push(pet.slug)
    }
  }
  void Promise.allSettled(pets.map((pet) => ensureSpritesheetCached(pet)))
  return { ok: true, pets, cachedSlugs }
}

export async function resolvePetSpritesheet(
  slugInput: string | undefined
): Promise<PetSpritesheetResolveResult> {
  const slug = normalizePetSlug(slugInput)
  const localCached = await readCachedSpritesheet(slug)
  if (localCached) {
    return {
      ok: true,
      slug,
      mime: 'image/webp',
      base64: localCached.toString('base64'),
      cached: true
    }
  }

  const manifestResult = await fetchPetManifest()
  if (!manifestResult.ok) {
    return { ok: false, message: manifestResult.message }
  }

  const entry =
    manifestResult.manifest.pets.find((pet) => pet.slug === slug) ??
    manifestResult.manifest.pets.find((pet) => pet.slug === DEFAULT_PET_SLUG)

  if (!entry) {
    return { ok: false, message: `Pet "${slug}" was not found in manifest.` }
  }

  try {
    await ensureSpritesheetCached(entry)
  } catch (error) {
    return {
      ok: false,
      message: error instanceof Error ? error.message : String(error)
    }
  }

  const cached = await readCachedSpritesheet(entry.slug)

  if (!cached) {
    return { ok: false, message: 'Failed to read cached spritesheet.' }
  }

  return {
    ok: true,
    slug: entry.slug,
    mime: 'image/webp',
    base64: cached.toString('base64'),
    cached: Boolean(cached)
  }
}
