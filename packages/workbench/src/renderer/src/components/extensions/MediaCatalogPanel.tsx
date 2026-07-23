import type { ReactElement } from 'react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronRight, Loader2, Search, X } from 'lucide-react'
import {
  extractBearerFromEntry,
  MEDIA_CATALOG,
  type MediaCatalogItem,
  buildTikhubServerEntry
} from './media-catalog'
import { ConnectorIcon } from './connector-icons'
import {
  getMcpServerEntry,
  isMcpServerEnabled,
  mcpConfigHasServer,
  type McpServerEntry
} from '../../lib/mcp-json-merge'

type Props = {
  mcpConfigText: string
  busyId: string | null
  onConfigure: (id: string, entry: McpServerEntry) => Promise<void>
  onToggle: (id: string, enabled: boolean) => Promise<void>
}

export function MediaCatalogPanel({
  mcpConfigText,
  busyId,
  onConfigure,
  onToggle
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const [query, setQuery] = useState('')
  const [active, setActive] = useState<MediaCatalogItem | null>(null)

  const items = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return MEDIA_CATALOG
    return MEDIA_CATALOG.filter(
      (item) =>
        item.id.toLowerCase().includes(q) ||
        item.title.toLowerCase().includes(q) ||
        item.description.toLowerCase().includes(q)
    )
  }, [query])

  return (
    <div className="ds-media-catalog px-5 py-5">
      <p className="ds-media-catalog__hint">{t('mediaCatalogHint')}</p>

      <div className="ds-media-catalog__search">
        <Search className="ds-media-catalog__search-icon" strokeWidth={1.9} aria-hidden />
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('mediaCatalogSearch')}
          className="ds-media-catalog__search-input"
          autoComplete="off"
          spellCheck={false}
        />
      </div>

      {items.length === 0 ? (
        <div className="py-12 text-center text-[13px] text-ds-faint">{t('mediaCatalogEmpty')}</div>
      ) : (
        <ul className="ds-media-catalog__grid">
          {items.map((item) => {
            const configured = mcpConfigHasServer(mcpConfigText, item.id)
            const entry = configured ? getMcpServerEntry(mcpConfigText, item.id) : null
            const enabled = entry ? isMcpServerEnabled(entry) : false
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => setActive(item)}
                  className="ds-media-catalog__card"
                >
                  <div className="ds-media-catalog__icon">
                    <ConnectorIcon
                      brand={item.brand}
                      connector={{
                        id: item.id,
                        name: item.title,
                        summary: item.description,
                        enabled: true
                      }}
                    />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="ds-media-catalog__title">{item.title}</span>
                      {configured ? (
                        <span
                          className={`ds-media-catalog__badge ${
                            enabled ? 'ds-media-catalog__badge--on' : ''
                          }`}
                        >
                          {enabled ? t('mediaCatalogConfigured') : t('mediaCatalogDisabled')}
                        </span>
                      ) : null}
                    </div>
                    <p className="ds-media-catalog__desc">{item.description}</p>
                  </div>
                  <ChevronRight className="ds-media-catalog__chevron" strokeWidth={1.8} aria-hidden />
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {active ? (
        <MediaConfigSheet
          item={active}
          mcpConfigText={mcpConfigText}
          busy={busyId === active.id}
          onClose={() => setActive(null)}
          onConfigure={onConfigure}
          onToggle={onToggle}
        />
      ) : null}
    </div>
  )
}

function MediaConfigSheet({
  item,
  mcpConfigText,
  busy,
  onClose,
  onConfigure,
  onToggle
}: {
  item: MediaCatalogItem
  mcpConfigText: string
  busy: boolean
  onClose: () => void
  onConfigure: (id: string, entry: McpServerEntry) => Promise<void>
  onToggle: (id: string, enabled: boolean) => Promise<void>
}): ReactElement {
  const { t } = useTranslation('common')
  const existing = mcpConfigHasServer(mcpConfigText, item.id)
    ? getMcpServerEntry(mcpConfigText, item.id)
    : null
  const [apiKey, setApiKey] = useState(() => extractBearerFromEntry(existing))
  const enabled = existing ? isMcpServerEnabled(existing) : false

  const save = async (): Promise<void> => {
    const key = apiKey.trim()
    if (!key) return
    await onConfigure(item.id, buildTikhubServerEntry(item, key))
    onClose()
  }

  return (
    <div className="ds-media-sheet-backdrop" onMouseDown={onClose}>
      <div
        className="ds-media-sheet"
        role="dialog"
        aria-modal="true"
        aria-labelledby={`media-sheet-${item.id}`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="ds-media-sheet__grab" aria-hidden />
        <div className="ds-media-sheet__header">
          <div className="ds-media-catalog__icon ds-media-catalog__icon--lg">
            <ConnectorIcon
              brand={item.brand}
              connector={{
                id: item.id,
                name: item.title,
                summary: item.description,
                enabled: true
              }}
            />
          </div>
          <div className="min-w-0 flex-1">
            <div id={`media-sheet-${item.id}`} className="ds-media-sheet__title">
              {item.title}
            </div>
            <p className="ds-media-sheet__subtitle">{item.description}</p>
            <p className="ds-media-sheet__id">@{item.id}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="ds-media-sheet__close"
            aria-label={t('close')}
          >
            <X className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </div>

        <div className="ds-media-sheet__body">
          <p className="ds-media-sheet__note">
            {t('mediaCatalogFocusHint', { name: item.id })}
          </p>
          <label className="ds-media-sheet__field">
            <span className="ds-media-sheet__label">{t('mediaCatalogApiKey')}</span>
            <input
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={t('mediaCatalogApiKeyPlaceholder')}
              className="ds-media-sheet__input"
            />
          </label>
        </div>

        <div className="ds-media-sheet__footer">
          {existing ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void onToggle(item.id, !enabled)}
              className="ds-media-sheet__btn ds-media-sheet__btn--ghost mr-auto"
            >
              {enabled ? t('mediaCatalogDisable') : t('mediaCatalogEnable')}
            </button>
          ) : null}
          <button type="button" onClick={onClose} className="ds-media-sheet__btn ds-media-sheet__btn--ghost">
            {t('cancel')}
          </button>
          <button
            type="button"
            disabled={busy || !apiKey.trim()}
            onClick={() => void save()}
            className="ds-media-sheet__btn ds-media-sheet__btn--primary"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} /> : null}
            {existing ? t('mediaCatalogUpdate') : t('mediaCatalogSave')}
          </button>
        </div>
      </div>
    </div>
  )
}
