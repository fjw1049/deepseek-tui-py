import { createHash } from 'node:crypto'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { PETDEX_MANIFEST_URL } from '../../shared/pet-manifest'

const cache = vi.hoisted(() => ({ root: '' }))
vi.mock('electron', () => ({ app: { getPath: () => cache.root } }))
vi.mock('../../shared/workbench-home', () => ({ resolveWorkbenchPetCacheDir: () => cache.root }))
vi.mock('../migrate-legacy-dir', () => ({ migrateLegacyDirContents: vi.fn() }))

let service: typeof import('./pet-asset-service')
let sprite: Buffer
const fetchMock = vi.fn()
const entry = {
  slug: 'boba', displayName: 'Boba', kind: 'creature', submittedBy: null,
  spritesheetUrl: 'https://assets.petdex.dev/new.webp', petJsonUrl: '', zipUrl: null
}
async function seed(spriteBytes: Buffer, url = entry.spritesheetUrl) {
  await writeFile(join(cache.root, 'boba.webp'), spriteBytes)
  await writeFile(join(cache.root, 'boba.meta'), createHash('sha256').update(url).digest('hex').slice(0, 16))
  await writeFile(join(cache.root, 'manifest.json'), JSON.stringify({
    fetchedAt: Date.now(), manifest: { pets: [{ ...entry, spritesheetUrl: url }], total: 1, generatedAt: '' }
  }))
}
beforeEach(async () => {
  cache.root = await mkdtemp(join(tmpdir(), 'pet-cache-test-'))
  sprite = await readFile('src/asset/pet/demo-spritesheet.webp')
  fetchMock.mockReset().mockRejectedValue(new Error('offline'))
  vi.stubGlobal('fetch', fetchMock)
  vi.resetModules()
  service = await import('./pet-asset-service')
})
afterEach(async () => { vi.unstubAllGlobals(); await rm(cache.root, { recursive: true, force: true }) })

it('serves a valid cached pet without any network dependency', async () => {
  await seed(sprite)
  const result = await service.resolvePetSpritesheet('boba')
  expect(result).toMatchObject({ ok: true, cached: true, base64: sprite.toString('base64') })
  expect(fetchMock).not.toHaveBeenCalled()
})

it('still serves a valid offline sprite when its manifest cache is malformed', async () => {
  await seed(sprite)
  await writeFile(join(cache.root, 'manifest.json'), JSON.stringify({
    fetchedAt: Date.now(), manifest: { pets: {} }
  }))
  expect(await service.resolvePetSpritesheet('boba')).toMatchObject({ ok: true, cached: true })
  expect(fetchMock).not.toHaveBeenCalled()
})

it('replaces a cached sprite after the refreshed manifest changes its URL', async () => {
  await seed(sprite, 'https://assets.petdex.dev/old.webp')
  fetchMock.mockImplementation(async url => url === PETDEX_MANIFEST_URL
    ? new Response(JSON.stringify({ pets: [entry] }))
    : new Response(new Uint8Array(sprite)))
  await service.fetchPetManifest(true)
  const result = await service.resolvePetSpritesheet('boba')
  expect(result.ok).toBe(true)
  expect(fetchMock).toHaveBeenCalledWith(entry.spritesheetUrl, expect.anything())
  expect(await readFile(join(cache.root, 'boba.meta'), 'utf8')).toBe(
    createHash('sha256').update(entry.spritesheetUrl).digest('hex').slice(0, 16)
  )
})

it('keeps the old sprite usable if a changed URL cannot be downloaded offline', async () => {
  await seed(sprite, 'https://assets.petdex.dev/old.webp')
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ pets: [entry] })))
  await service.fetchPetManifest(true)
  expect(await service.resolvePetSpritesheet('boba')).toMatchObject({
    ok: true, cached: true, base64: sprite.toString('base64')
  })
})

it.each(['html', 'truncated'])('repairs a %s cache entry instead of treating it as ready', async kind => {
  await seed(kind === 'html' ? Buffer.from('<html>error</html>') : sprite.subarray(0, 40))
  fetchMock.mockResolvedValue(new Response(new Uint8Array(sprite)))
  const result = await service.resolvePetSpritesheet('boba')
  expect(result).toMatchObject({ ok: true, base64: sprite.toString('base64') })
  expect(fetchMock).toHaveBeenCalledWith(entry.spritesheetUrl, expect.anything())
  expect(await readFile(join(cache.root, 'boba.webp'))).toEqual(sprite)
})

it('rejects a non-image download and leaves the previous valid cache intact', async () => {
  await seed(sprite, 'https://assets.petdex.dev/old.webp')
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ pets: [entry] })))
    .mockResolvedValueOnce(new Response('x'.repeat(512)))
  await service.fetchPetManifest(true)
  expect(await service.resolvePetSpritesheet('boba')).toMatchObject({ ok: true, base64: sprite.toString('base64') })
  expect(await readFile(join(cache.root, 'boba.webp'))).toEqual(sprite)
})

const popularBody = { pets: [
  { slug: 'capvolt', displayName: 'Pikachu\u200c', kind: 'creature', submittedBy: { name: 'Ann' },
    metrics: { likeCount: 68, installCount: 2826 } },
  { slug: '../evil', displayName: 'Nope' }
] }

it('fetches the most-liked pets, cleans names and caches the list', async () => {
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(popularBody)))
  const live = await service.fetchPopularPets()
  expect(live).toEqual({ source: 'live', pets: [{
    slug: 'capvolt', displayName: 'Pikachu', kind: 'creature', submittedBy: 'Ann', likeCount: 68, installCount: 2826
  }] })
  expect(fetchMock.mock.calls[0]![0]).toBe('https://petdex.dev/api/pets/search?sort=popular&limit=30')
  vi.resetModules()
  service = await import('./pet-asset-service')
  await expect(service.fetchPopularPets()).resolves.toMatchObject({ source: 'cache', pets: [{ slug: 'capvolt' }] })
  expect(fetchMock).toHaveBeenCalledOnce()
})

it('falls back to the bundled ranking when offline with nothing cached', async () => {
  const result = await service.fetchPopularPets()
  expect(result.source).toBe('bundled')
  expect(result.pets).toHaveLength(30)
  expect(result.message).toBe('offline')
})

it('fetches thumbnails once, then serves them from disk', async () => {
  fetchMock.mockImplementation(async (url: string) => url.endsWith('/boba/thumb.webp')
    ? new Response(new Uint8Array(sprite)) : new Response('missing', { status: 404 }))
  const first = await service.resolvePetThumbnails(['boba', 'ghost', 'bad slug!'])
  expect(first.boba).toBe(`data:image/webp;base64,${sprite.toString('base64')}`)
  expect(first.ghost).toBeNull()
  expect(first).not.toHaveProperty('bad slug!')
  fetchMock.mockClear()
  await expect(service.resolvePetThumbnails(['boba'])).resolves.toEqual({ boba: first.boba })
  expect(fetchMock).not.toHaveBeenCalled()
})
