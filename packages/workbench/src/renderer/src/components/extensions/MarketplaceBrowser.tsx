import type { ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, ExternalLink, Loader2, Plus, RefreshCw } from 'lucide-react'
import type { MarketplaceCategory, MarketplaceItem, MarketplaceKind } from '../../../../shared/ds-gui-api'
import type { Notice } from './marketplace-shared'
import { NoticeView } from './marketplace-ui'

export type InstallOutcome = { tone: Notice['tone']; message: string }

type MarketplaceBrowserProps = {
  kind: MarketplaceKind
  /** Renderer-side install; returns a notice to show. `null` = installed silently. */
  onInstall: (item: MarketplaceItem) => Promise<InstallOutcome | null>
  /** Whether an item is already installed (checked against the parent's state). */
  isInstalled: (item: MarketplaceItem) => boolean
  /** Free-text query owned by the parent page's search box. */
  query: string
}

export function MarketplaceBrowser({ kind, onInstall, isInstalled, query }: MarketplaceBrowserProps): ReactElement {
  const { t } = useTranslation('common')
  const [items, setItems] = useState<MarketplaceItem[]>([])
  const [categories, setCategories] = useState<MarketplaceCategory[]>([])
  const [activeCategory, setActiveCategory] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [stale, setStale] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)

  const load = useCallback(
    async (force: boolean): Promise<void> => {
      const api = force ? window.dsGui?.refreshMarketplaceCatalog : window.dsGui?.getMarketplaceCatalog
      if (typeof api !== 'function') return
      if (force) setRefreshing(true)
      else setLoading(true)
      setError(null)
      try {
        const result = await api(kind)
        if (result.ok) {
          setItems(result.items)
          setCategories(result.categories)
          setStale(result.stale)
        } else {
          setError(result.error)
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
        setRefreshing(false)
      }
    },
    [kind]
  )

  useEffect(() => {
    void load(false)
  }, [load])

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
    <section className="mt-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-[20px] font-semibold text-ds-ink">{t('marketplaceTitle')}</h2>
        <button
          type="button"
          onClick={() => void load(true)}
          disabled={refreshing || loading}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-ds-subtle px-3 py-2 text-[13px] font-semibold leading-none text-ds-ink transition hover:bg-ds-hover disabled:opacity-55"
        >
          {refreshing ? (
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
          ) : (
            <RefreshCw className="h-4 w-4" strokeWidth={1.9} />
          )}
          {t('marketplaceRefresh')}
        </button>
      </div>

      {categories.length > 0 ? (
        <div className="mt-4 flex flex-wrap gap-2">
          <CategoryChip
            label={t('marketplaceCategoryAll')}
            active={activeCategory === null}
            onClick={() => setActiveCategory(null)}
          />
          {categories.map((cat) => (
            <CategoryChip
              key={cat.value}
              label={cat.value}
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
      ) : filtered.length === 0 ? (
        <div className="py-8 text-[14px] text-ds-faint">{t('pluginNoResults')}</div>
      ) : (
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
    </section>
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
