import type { ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, ExternalLink, Loader2, Plus } from 'lucide-react'
import type { MarketplaceCategory, MarketplaceItem, MarketplaceKind } from '../../../../shared/ds-gui-api'
import type { Notice } from './marketplace-shared'
import { NoticeView } from './marketplace-ui'

export type InstallOutcome = { tone: Notice['tone']; message: string }

/**
 * ModelScope's API only returns English category values (PascalCase for skills,
 * kebab-case slugs for MCP). There is no Chinese field upstream, so we map the
 * known values to Chinese labels for display when the UI is Chinese. Filtering
 * still uses the raw `value`; unknown values fall back to the original string.
 */
const CATEGORY_ZH: Record<string, string> = {
  // skill L1 categories
  MediaAI: '媒体 AI',
  Skills: '技能',
  DevTools: '开发工具',
  Frontend: '前端',
  Marketing: '营销',
  // mcp category slugs
  'developer-tools': '开发工具',
  search: '搜索',
  databases: '数据库',
  'browser-automation': '浏览器自动化',
  other: '其他',
  'knowledge-and-memory': '知识与记忆',
  'cloud-platforms': '云平台',
  'os-automation': '系统自动化',
  communication: '通讯',
  finance: '金融',
  'research-and-data': '研究与数据',
  'file-systems': '文件系统',
  'art-and-culture': '艺术与文化',
  'entertainment-and-media': '娱乐与媒体',
  'calendar-management': '日历管理',
  'location-services': '位置服务',
  'travel-and-transportation': '出行与交通',
  'version-control': '版本控制',
  // MCP items occasionally carry spaced/PascalCase variants — map those too.
  AIGC: 'AIGC',
  Search: '搜索',
  'Knowledge & Memory': '知识与记忆'
}

function displayCategory(value: string, language: string): string {
  return language.startsWith('zh') ? (CATEGORY_ZH[value] ?? value) : value
}

type MarketplaceBrowserProps = {
  kind: MarketplaceKind
  /** Renderer-side install; returns a notice to show. `null` = installed silently. */
  onInstall: (item: MarketplaceItem) => Promise<InstallOutcome | null>
  /** Whether an item is already installed (checked against the parent's state). */
  isInstalled: (item: MarketplaceItem) => boolean
  /** Free-text query owned by the parent page's search box. */
  query: string
  /** Parent-driven refresh trigger. Each increment forces a network re-fetch
   * of the ModelScope catalog (bypassing the disk cache). The parent's top
   * "重新加载" button bumps this so the market tab stays in sync with the
   * built-in / installed lists without a second refresh button in-tab. */
  refreshSignal?: number
}

export function MarketplaceBrowser({ kind, onInstall, isInstalled, query, refreshSignal }: MarketplaceBrowserProps): ReactElement {
  const { t, i18n } = useTranslation('common')
  const [items, setItems] = useState<MarketplaceItem[]>([])
  const [activeCategory, setActiveCategory] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [stale, setStale] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)

  const load = useCallback(
    async (force: boolean): Promise<void> => {
      const api = force ? window.dsGui?.refreshMarketplaceCatalog : window.dsGui?.getMarketplaceCatalog
      if (typeof api !== 'function') return
      setLoading(true)
      setError(null)
      try {
        const result = await api(kind)
        if (result.ok) {
          // Normalize per-item categories (trim whitespace; the MCP API returns
          // inconsistent leading spaces and the server-side FiledAgg aggregation
          // includes categories no listed item actually references).
          setItems(
            result.items.map((item) => ({
              ...item,
              categories: item.categories.map((c) => c.trim()).filter(Boolean)
            }))
          )
          setStale(result.stale)
        } else {
          setError(result.error)
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    },
    [kind]
  )

  useEffect(() => {
    void load(false)
  }, [load])

  // Parent-driven refresh: when the parent's top "重新加载" button bumps
  // `refreshSignal`, force a network re-fetch. Skip the initial mount so we
  // don't bypass the disk cache on first render (the effect above already
  // loads the cached catalog).
  const prevRefreshSignalRef = useRef(refreshSignal ?? 0)
  useEffect(() => {
    const prev = prevRefreshSignalRef.current
    prevRefreshSignalRef.current = refreshSignal ?? 0
    if (refreshSignal === undefined || refreshSignal === prev) return
    void load(true)
  }, [refreshSignal, load])

  // Derive category chips from the items actually present, so every chip always
  // maps to ≥1 item. The server's `categories` aggregation is ignored for display
  // because it can include categories that no returned item references.
  const derivedCategories = useMemo<MarketplaceCategory[]>(() => {
    const counts = new Map<string, number>()
    for (const item of items) {
      for (const cat of item.categories) {
        const value = cat.trim()
        if (!value) continue
        counts.set(value, (counts.get(value) ?? 0) + 1)
      }
    }
    return Array.from(counts.entries())
      .map(([value, count]) => ({ value, count }))
      .sort((a, b) => b.count - a.count)
  }, [items])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return items.filter((item) => {
      if (activeCategory && !item.categories.includes(activeCategory)) return false
      if (!q) return true
      return item.name.toLowerCase().includes(q) || item.description.toLowerCase().includes(q)
    })
  }, [items, query, activeCategory])

  const install = async (item: MarketplaceItem): Promise<void> => {
    setBusyId(item.id)
    setNotice(null)
    try {
      const outcome = await onInstall(item)
      if (outcome) setNotice(outcome)
    } catch (e) {
      setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="px-5 py-4">
      {derivedCategories.length > 0 ? (
        <div className="flex flex-wrap gap-2">
          <CategoryChip
            label={t('marketplaceCategoryAll')}
            active={activeCategory === null}
            onClick={() => setActiveCategory(null)}
          />
          {derivedCategories.map((cat) => (
            <CategoryChip
              key={cat.value}
              label={displayCategory(cat.value, i18n.language)}
              active={activeCategory === cat.value}
              onClick={() => setActiveCategory((prev) => (prev === cat.value ? null : cat.value))}
            />
          ))}
        </div>
      ) : null}

      {stale ? <NoticeView notice={{ tone: 'info', message: t('marketplaceStale') }} /> : null}
      {notice ? <NoticeView notice={notice} /> : null}

      {loading ? (
        <div className="flex items-center gap-2 py-10 text-[14px] text-ds-faint">
          <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
          {t('marketplaceLoading')}
        </div>
      ) : error ? (
        <NoticeView notice={{ tone: 'error', message: t('marketplaceLoadFailed', { error }) }} />
      ) : filtered.length === 0 ? null : (
        <div className="mt-4 grid gap-x-14 md:grid-cols-2">
          {filtered.map((item) => {
            const installed = isInstalled(item)
            const busy = busyId === item.id
            return (
              <div
                key={item.id}
                className="ds-content-card ds-content-card--interactive my-2 flex min-h-[92px] items-center gap-5 rounded-2xl px-4 py-4"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-[17px] font-semibold text-ds-ink">{item.name}</span>
                    {item.publisher ? (
                      <span className="shrink-0 rounded-md bg-ds-subtle px-1.5 py-0.5 text-[11px] font-medium text-ds-muted">
                        {item.publisher}
                      </span>
                    ) : null}
                  </div>
                  <p className="mt-1 line-clamp-2 text-[14px] leading-5 text-ds-muted">{item.description}</p>
                </div>
                <button
                  type="button"
                  disabled={installed || busy}
                  onClick={() => void install(item)}
                  title={installed ? t('marketplaceInstalled') : t('marketplaceInstall')}
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition ${
                    installed ? 'text-ds-faint' : 'bg-ds-subtle text-ds-ink hover:bg-ds-hover disabled:opacity-60'
                  }`}
                >
                  {busy ? (
                    <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
                  ) : installed ? (
                    <Check className="h-4 w-4" strokeWidth={2} />
                  ) : (
                    <Plus className="h-4 w-4" strokeWidth={2} />
                  )}
                </button>
              </div>
            )
          })}
        </div>
      )}

      <div className="mt-4 flex items-center gap-1.5 text-[12px] text-ds-faint">
        <ExternalLink className="h-3.5 w-3.5" />
        <span>{t('marketplacePoweredBy')}</span>
      </div>
    </div>
  )
}

function CategoryChip({
  label,
  active,
  onClick
}: {
  label: string
  active: boolean
  onClick: () => void
}): ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1.5 text-[12px] font-medium leading-none transition ${
        active ? 'bg-ds-userbubble text-ds-userbubbleFg' : 'bg-ds-subtle text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
      }`}
    >
      {label}
    </button>
  )
}
