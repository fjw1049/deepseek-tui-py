import { app } from 'electron'
import { createHash } from 'node:crypto'
import { access, mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'

import type {
  PetManifestFetchResult,
  PetManifestEntry,
  PetManifestSlim,
  PetSpritesheetResolveResult
} from '../../shared/pet-manifest'
import { DEFAULT_PET_SLUG, PETDEX_MANIFEST_URL } from '../../shared/pet-manifest'
import {
  BUNDLED_POPULAR_PETS,
  cleanPetDisplayName,
  parsePopularPets,
  PET_POPULAR_LIMIT,
  PETDEX_POPULAR_URL,
  petThumbnailUrl,
  type PetPopularEntry,
  type PetPopularResult,
  type PetThumbnailResult
} from '../../shared/pet-popular'
import { isAllowedManifestUrl, isAllowedSpritesheetUrl } from '../../shared/pet-url-allowlist'
import { resolveWorkbenchPetCacheDir } from '../../shared/workbench-home'
import { migrateLegacyDirContents } from '../migrate-legacy-dir'

const MANIFEST_TTL_MS = 5 * 60 * 1000
const FETCH_TIMEOUT_MS = 20_000
const PET_SLUG_PATTERN = /^[a-z0-9][a-z0-9_-]{0,79}$/i

type ManifestCacheRecord = {
  fetchedAt: number
  manifest: PetManifestSlim
}

let memoryManifest: ManifestCacheRecord | null = null
let cacheReady: Promise<void> | null = null

function cacheRoot(): string {
  return resolveWorkbenchPetCacheDir()
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
  if (!cacheReady) {
    cacheReady = (async () => {
      const dest = cacheRoot()
      await migrateLegacyDirContents(join(app.getPath('userData'), 'pet-cache'), dest)
      await mkdir(dest, { recursive: true })
    })()
  }
  await cacheReady
}

async function readManifestCacheFile(): Promise<ManifestCacheRecord | null> {
  try {
    const raw = await readFile(manifestCachePath(), 'utf8')
    const parsed = JSON.parse(raw) as ManifestCacheRecord
    const manifest = parseManifestBody(parsed?.manifest)
    if (!manifest || typeof parsed.fetchedAt !== 'number') return null
    return { fetchedAt: parsed.fetchedAt, manifest }
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
      const displayName = typeof item.displayName === 'string' ? cleanPetDisplayName(item.displayName) : ''
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
  // Ensure the workbench pet-cache exists and legacy Electron userData
  // spritesheets are migrated before any read/write.
  await ensureCacheDir()

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

function isCompleteWebp(buffer: Buffer): boolean {
  return buffer.length >= 12 && buffer.toString('ascii', 0, 4) === 'RIFF' &&
    buffer.toString('ascii', 8, 12) === 'WEBP' && buffer.readUInt32LE(4) + 8 === buffer.length
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
    if (!isCompleteWebp(buffer)) {
      throw new Error('Spritesheet payload was not a complete WebP image.')
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
    const buffer = await readFile(spritesheetCachePath(slug))
    return isCompleteWebp(buffer) ? buffer : null
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

export async function resolvePetSpritesheet(
  slugInput: string | undefined
): Promise<PetSpritesheetResolveResult> {
  const slug = normalizePetSlug(slugInput)
  // Migrate legacy cache before the first local read so previously downloaded
  // pets keep working offline after the workbench-home consolidation.
  await ensureCacheDir()

  const localCached = await readCachedSpritesheet(slug)
  // Consult an already known catalog before accepting a cached sprite. Do not
  // require a network manifest request just to display an offline pet.
  const knownManifest = memoryManifest ?? await readManifestCacheFile()
  let entry = knownManifest?.manifest.pets.find((pet) => pet.slug === slug)
  if (localCached && (!entry || await isSpritesheetCacheFresh(entry))) {
    return {
      ok: true, slug, mime: 'image/webp',
      base64: localCached.toString('base64'), cached: true
    }
  }

  if (!entry) {
    const manifestResult = await fetchPetManifest()
    if (!manifestResult.ok) return { ok: false, message: manifestResult.message }
    entry = manifestResult.manifest.pets.find((pet) => pet.slug === slug) ??
      manifestResult.manifest.pets.find((pet) => pet.slug === DEFAULT_PET_SLUG)
  }

  if (!entry) {
    return { ok: false, message: `Pet "${slug}" was not found in manifest.` }
  }

  try {
    await ensureSpritesheetCached(entry)
  } catch (error) {
    if (localCached) {
      return {
        ok: true, slug, mime: 'image/webp',
        base64: localCached.toString('base64'), cached: true
      }
    }
    return { ok: false, message: error instanceof Error ? error.message : String(error) }
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

const POPULAR_TTL_MS = 12 * 60 * 60 * 1000
const THUMBNAIL_CONCURRENCY = 6

type PopularCacheRecord = { fetchedAt: number; pets: PetPopularEntry[] }

let memoryPopular: PopularCacheRecord | null = null

function popularCachePath(): string {
  // Keyed by size so a list cached under an older limit is not reused.
  return join(cacheRoot(), `popular-${PET_POPULAR_LIMIT}.json`)
}

function thumbnailCachePath(slug: string): string {
  return join(cacheRoot(), 'thumbs', `${slug}.webp`)
}

async function readPopularCacheFile(): Promise<PopularCacheRecord | null> {
  try {
    const parsed = JSON.parse(await readFile(popularCachePath(), 'utf8')) as PopularCacheRecord
    const pets = parsePopularPets({ pets: parsed?.pets }, (slug) => PET_SLUG_PATTERN.test(slug))
    return typeof parsed?.fetchedAt === 'number' && pets.length ? { fetchedAt: parsed.fetchedAt, pets } : null
  } catch {
    return null
  }
}

async function fetchPopularRemote(): Promise<PetPopularEntry[]> {
  if (!isAllowedManifestUrl(PETDEX_POPULAR_URL)) throw new Error('Popular pets URL is not allowlisted.')
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
  try {
    const response = await fetch(PETDEX_POPULAR_URL, {
      signal: controller.signal,
      headers: { Accept: 'application/json' }
    })
    if (!response.ok) throw new Error(`Popular pets request failed (${response.status}).`)
    const pets = parsePopularPets(await response.json(), (slug) => PET_SLUG_PATTERN.test(slug))
    if (!pets.length) throw new Error('Popular pets response was empty or invalid.')
    return pets
  } finally {
    clearTimeout(timer)
  }
}

/**
 * The 30 most-liked pets on Petdex. Falls back to the last good list, then to
 * the snapshot shipped with the app, so Settings always has something to show.
 */
export async function fetchPopularPets(force = false): Promise<PetPopularResult> {
  await ensureCacheDir()
  const now = Date.now()
  if (!force && memoryPopular && now - memoryPopular.fetchedAt < POPULAR_TTL_MS) {
    return { pets: memoryPopular.pets, source: 'cache' }
  }
  const disk = memoryPopular ?? await readPopularCacheFile()
  if (!force && disk && now - disk.fetchedAt < POPULAR_TTL_MS) {
    memoryPopular = disk
    return { pets: disk.pets, source: 'cache' }
  }
  try {
    const pets = await fetchPopularRemote()
    memoryPopular = { fetchedAt: now, pets }
    await writeFile(popularCachePath(), JSON.stringify(memoryPopular), 'utf8')
    return { pets, source: 'live' }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (disk) return { pets: disk.pets, source: 'cache', message }
    return { pets: [...BUNDLED_POPULAR_PETS], source: 'bundled', message }
  }
}

async function resolveOneThumbnail(slug: string): Promise<string | null> {
  const path = thumbnailCachePath(slug)
  try {
    const cached = await readFile(path)
    if (isCompleteWebp(cached)) return `data:image/webp;base64,${cached.toString('base64')}`
  } catch {
    // Not cached yet.
  }
  const url = petThumbnailUrl(slug)
  if (!isAllowedSpritesheetUrl(url)) return null
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
  try {
    const response = await fetch(url, { signal: controller.signal })
    if (!response.ok) return null
    const buffer = Buffer.from(await response.arrayBuffer())
    if (!isCompleteWebp(buffer)) return null
    await mkdir(join(cacheRoot(), 'thumbs'), { recursive: true })
    await writeFile(path, buffer)
    return `data:image/webp;base64,${buffer.toString('base64')}`
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

/** Small (~2 KB) Petdex thumbnails for the picker, cached on disk after the first fetch. */
export async function resolvePetThumbnails(slugs: string[]): Promise<PetThumbnailResult> {
  await ensureCacheDir()
  const unique = [...new Set(slugs.filter((slug) => PET_SLUG_PATTERN.test(slug)))]
  const result: PetThumbnailResult = {}
  let next = 0
  const worker = async (): Promise<void> => {
    while (next < unique.length) {
      const slug = unique[next++]!
      result[slug] = await resolveOneThumbnail(slug)
    }
  }
  await Promise.all(Array.from({ length: Math.min(THUMBNAIL_CONCURRENCY, unique.length) }, worker))
  return result
}
