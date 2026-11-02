/** Pets ranked by Petdex likes, as shown in Settings → Desktop pet. */

export const PETDEX_POPULAR_URL = 'https://petdex.dev/api/pets/search?sort=popular&limit=60'
/** Petdex caps one search page at 60. */
export const PET_POPULAR_LIMIT = 60

export type PetPopularEntry = {
  slug: string
  displayName: string
  kind: string
  submittedBy: string | null
  likeCount: number | null
  installCount: number | null
}

export type PetPopularResult = {
  pets: PetPopularEntry[]
  /** live: fetched now; cache: last good fetch; bundled: offline snapshot shipped with the app. */
  source: 'live' | 'cache' | 'bundled'
  message?: string
}

/** Thumbnail data URLs by slug; null when one could not be fetched. */
export type PetThumbnailResult = Record<string, string | null>

const INVISIBLE = /[\u200B-\u200D\u2060\uFEFF]/g

export function cleanPetDisplayName(value: string): string {
  return value.replace(INVISIBLE, '').trim()
}

const snapshot = (slug: string, displayName: string, kind: string): PetPopularEntry => ({
  slug, displayName, kind, submittedBy: null, likeCount: null, installCount: null
})

/** Top 60 by likes on 2026-11-02, used until the live ranking loads or when offline. */
export const BUNDLED_POPULAR_PETS: readonly PetPopularEntry[] = [
  snapshot('nezukocoder', 'NezukoCoder', 'character'),
  snapshot('capvolt', 'Pikachu', 'creature'),
  snapshot('lulu-capybara-2', '噜噜', 'creature'),
  snapshot('shinchan', 'Shinchan', 'character'),
  snapshot('yuexinmiao', '月薪喵', 'character'),
  snapshot('doraemon', 'Doraemon', 'character'),
  snapshot('qqpet-codex', 'QQpet-codex', 'object'),
  snapshot('jokebear-codexpet', 'JokeBear-CodexPet', 'character'),
  snapshot('deepseek', 'deepseek酱', 'character'),
  snapshot('round-maodie-c63864e8', '圆头耄耋', 'character'),
  snapshot('noir-webling', 'Noir Webling', 'creature'),
  snapshot('usagi', 'Usagi', 'creature'),
  snapshot('hachiware-2', '小八', 'creature'),
  snapshot('eve', 'EVE', 'character'),
  snapshot('bananacat', 'BananaCat', 'creature'),
  snapshot('einstein', 'Einstein', 'character'),
  snapshot('kirby', 'Kirby', 'character'),
  snapshot('doubao-2', '豆包', 'character'),
  snapshot('kabi', '卡比兽', 'creature'),
  snapshot('hoops', 'Hoops', 'character'),
  snapshot('tiko', 'Tiko', 'character'),
  snapshot('capoo', 'capoo', 'creature'),
  snapshot('oiiai', 'oiiai', 'creature'),
  snapshot('kurisu', 'Kurisu', 'character'),
  snapshot('vivimi-strict', '维维美', 'character'),
  snapshot('paimo-2', 'Super Paimon', 'character'),
  snapshot('violet-mage', 'Violet Mage', 'character'),
  snapshot('a-tom', 'A Tom', 'creature'),
  snapshot('kun-like', 'Kun Like', 'character'),
  snapshot('aniya', 'Aniya', 'character'),
  snapshot('daodun', 'DaoDun', 'creature'),
  snapshot('doodlebob', 'Doodle Bob', 'character'),
  snapshot('gojo', 'Gojo', 'character'),
  snapshot('goku', 'Goku', 'character'),
  snapshot('itachi', 'Itachi', 'character'),
  snapshot('nezuko', 'Nezuko', 'character'),
  snapshot('nightleaf', 'Xiao Hei', 'creature'),
  snapshot('yinyue-2', '银月', 'creature'),
  snapshot('duo', 'Duo', 'character'),
  snapshot('luffy', 'Luffy', 'character'),
  snapshot('pingu', 'Pingu', 'character'),
  snapshot('naifrog-2-0', '奶蛙2.0', 'creature'),
  snapshot('gugugaga-2', '咕咕嘎嘎', 'creature'),
  snapshot('bellylaugh', '奶龙', 'creature'),
  snapshot('phoebibi', '菲比', 'character'),
  snapshot('wangcai', 'Wangcai', 'creature'),
  snapshot('jiyi', '吉伊', 'creature'),
  snapshot('albedo-real-crisp', 'Albedo Real Crisp', 'character'),
  snapshot('rx-78-2-gundam', 'RX-78-2 Gundam', 'character'),
  snapshot('zoro', 'Zoro', 'character'),
  snapshot('frieren-3', 'Frieren', 'character'),
  snapshot('hachiware', 'Hachiware', 'creature'),
  snapshot('pochita-mini', 'Pochita Mini', 'creature'),
  snapshot('anya-2', '阿尼亚', 'character'),
  snapshot('doro-2', 'Doro', 'creature'),
  snapshot('maltese', 'Maltese', 'creature'),
  snapshot('salty-clerk', 'Salty Clerk', 'creature'),
  snapshot('silver-wolf-lv999', '银狼 Lv999', 'character'),
  snapshot('rem-xl', '雷姆', 'character'),
  snapshot('boba', 'Boba', 'creature')
]

export function petThumbnailUrl(slug: string): string {
  return `https://assets.petdex.dev/pets/${encodeURIComponent(slug)}/thumb.webp`
}

const count = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.floor(value) : null

/** Parses a /api/pets/search response; entries without a usable slug or name are dropped. */
export function parsePopularPets(body: unknown, isValidSlug: (slug: string) => boolean): PetPopularEntry[] {
  const pets = body && typeof body === 'object' ? (body as { pets?: unknown }).pets : null
  if (!Array.isArray(pets)) return []
  return pets.flatMap((raw): PetPopularEntry[] => {
    if (!raw || typeof raw !== 'object') return []
    const item = raw as Record<string, unknown>
    const slug = typeof item.slug === 'string' ? item.slug.trim() : ''
    const displayName = typeof item.displayName === 'string' ? cleanPetDisplayName(item.displayName) : ''
    if (!slug || !isValidSlug(slug) || !displayName) return []
    const metrics = item.metrics && typeof item.metrics === 'object' ? item.metrics as Record<string, unknown> : {}
    const author = item.submittedBy && typeof item.submittedBy === 'object'
      ? (item.submittedBy as { name?: unknown }).name
      : item.submittedBy
    return [{
      slug,
      displayName,
      kind: typeof item.kind === 'string' ? item.kind : 'creature',
      submittedBy: typeof author === 'string' && author.trim() ? author.trim() : null,
      likeCount: count(metrics.likeCount),
      installCount: count(metrics.installCount)
    }]
  }).slice(0, PET_POPULAR_LIMIT)
}
