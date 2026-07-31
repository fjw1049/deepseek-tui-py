import { useMemo, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent
} from '@dnd-kit/core'
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Eye, EyeOff, GripVertical } from 'lucide-react'
import {
  defaultWebSearchSettings,
  normalizeWebSearchOrder,
  type AppSettingsPatch,
  type AppSettingsV1,
  type WebSearchProviderId,
  type WebSearchSettingsV1
} from '@shared/app-settings'
import { moveIdBefore } from '../../lib/sidebar-manual-order'

type Props = {
  form: AppSettingsV1
  onUpdate: (patch: AppSettingsPatch) => void
}

const NAME_KEY: Record<WebSearchProviderId, string> = {
  anysearch: 'webSearchProviderAnysearch',
  tavily: 'webSearchProviderTavily'
}

const HINT_KEY: Record<WebSearchProviderId, string> = {
  anysearch: 'webSearchProviderAnysearchHint',
  tavily: 'webSearchProviderTavilyHint'
}

export function WebSearchSettingsPanel({ form, onUpdate }: Props): ReactElement {
  const { t } = useTranslation('settings')
  const webSearch = form.webSearch ?? defaultWebSearchSettings()
  const order = useMemo(
    () => normalizeWebSearchOrder(webSearch.order),
    [webSearch.order]
  )
  const [showKey, setShowKey] = useState<Record<WebSearchProviderId, boolean>>({
    anysearch: false,
    tavily: false
  })

  const sensors = useSensors(
    useSensor(PointerSensor, {
      // Keep clicks on toggle / inputs working; drag needs a short move.
      activationConstraint: { distance: 8 }
    })
  )

  const commitOrder = (nextOrder: WebSearchProviderId[]): void => {
    const normalized = normalizeWebSearchOrder(nextOrder)
    if (normalized.join('\0') === order.join('\0')) return
    // Persist the full webSearch object so partial merges cannot drop order.
    const next: WebSearchSettingsV1 = {
      order: normalized,
      providers: {
        anysearch: { ...webSearch.providers.anysearch },
        tavily: { ...webSearch.providers.tavily }
      }
    }
    onUpdate({ webSearch: next })
  }

  const patchProvider = (
    id: WebSearchProviderId,
    patch: Partial<WebSearchSettingsV1['providers'][WebSearchProviderId]>
  ): void => {
    onUpdate({
      webSearch: {
        order,
        providers: {
          anysearch: { ...webSearch.providers.anysearch },
          tavily: { ...webSearch.providers.tavily },
          [id]: { ...webSearch.providers[id], ...patch }
        }
      }
    })
  }

  const handleDragEnd = (event: DragEndEvent): void => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const activeId = String(active.id)
    const overId = String(over.id)
    if (!order.includes(activeId as WebSearchProviderId)) return
    if (!order.includes(overId as WebSearchProviderId)) return
    commitOrder(moveIdBefore(order, activeId, overId) as WebSearchProviderId[])
  }

  return (
    <section className="ds-content-card rounded-2xl">
      <div className="border-b border-ds-border-muted px-5 py-3">
        <h2 className="text-[16px] font-semibold text-ds-ink">{t('sectionWebSearch')}</h2>
        <p className="mt-1 text-[13px] leading-5 text-ds-muted">{t('webSearchSectionDesc')}</p>
      </div>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={order} strategy={verticalListSortingStrategy}>
          <div className="divide-y divide-ds-border-muted px-2 py-1">
            {order.map((id, index) => (
              <SortableProviderCard
                key={id}
                id={id}
                index={index}
                enabled={webSearch.providers[id].enabled}
                apiKey={webSearch.providers[id].apiKey}
                showKey={showKey[id]}
                onToggleShowKey={() =>
                  setShowKey((prev) => ({ ...prev, [id]: !prev[id] }))
                }
                onEnabledChange={(enabled) => patchProvider(id, { enabled })}
                onApiKeyChange={(apiKey) => patchProvider(id, { apiKey })}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>
    </section>
  )
}

function SortableProviderCard({
  id,
  index,
  enabled,
  apiKey,
  showKey,
  onToggleShowKey,
  onEnabledChange,
  onApiKeyChange
}: {
  id: WebSearchProviderId
  index: number
  enabled: boolean
  apiKey: string
  showKey: boolean
  onToggleShowKey: () => void
  onEnabledChange: (enabled: boolean) => void
  onApiKeyChange: (apiKey: string) => void
}): ReactElement {
  const { t } = useTranslation('settings')
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id
  })
  const keyRequired = id === 'tavily'
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    zIndex: isDragging ? 20 : undefined,
    position: 'relative' as const,
    opacity: isDragging ? 0.92 : 1
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`ds-density-row flex flex-col gap-3 px-4 py-5 ${
        isDragging ? 'rounded-xl bg-ds-card shadow-lg ring-1 ring-ds-border' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-2">
          <button
            type="button"
            className="mt-0.5 cursor-grab touch-none rounded-md p-1 text-ds-muted hover:bg-ds-hover hover:text-ds-ink active:cursor-grabbing"
            aria-label={t('webSearchDragHandle')}
            title={t('webSearchDragHandle')}
            {...attributes}
            {...listeners}
          >
            <GripVertical className="h-4 w-4" strokeWidth={1.9} />
          </button>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2 text-[14px] font-semibold text-ds-ink">
              <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-md bg-ds-subtle px-1.5 text-[11px] font-medium text-ds-muted">
                {index + 1}
              </span>
              <span>{t(NAME_KEY[id])}</span>
              {index === 0 ? (
                <span className="text-[11px] font-medium text-accent">
                  {t('webSearchPriorityPrimary')}
                </span>
              ) : null}
            </div>
            <p className="mt-1 max-w-2xl text-[13px] leading-6 text-ds-muted">{t(HINT_KEY[id])}</p>
          </div>
        </div>
        <Toggle checked={enabled} onChange={onEnabledChange} />
      </div>
      <div className="relative w-full min-w-0 pl-8">
        <input
          type={showKey ? 'text' : 'password'}
          className="w-full min-w-0 rounded-xl border border-ds-border bg-ds-card px-3 py-2 pr-10 text-[14px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
          value={apiKey}
          placeholder={keyRequired ? 'tvly-…' : t('webSearchOptionalKeyPlaceholder')}
          onChange={(e) => onApiKeyChange(e.target.value)}
        />
        <button
          type="button"
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded-md p-1 text-ds-muted hover:bg-ds-hover hover:text-ds-ink"
          onClick={onToggleShowKey}
          aria-label={t('llmApiKey')}
        >
          {showKey ? (
            <EyeOff className="h-4 w-4" strokeWidth={1.75} />
          ) : (
            <Eye className="h-4 w-4" strokeWidth={1.75} />
          )}
        </button>
      </div>
      <p className="pl-8 text-[12px] leading-5 text-ds-muted">
        {keyRequired ? t('webSearchTavilyKeyHint') : t('webSearchAnysearchKeyHint')}
      </p>
    </div>
  )
}

function Toggle({
  checked,
  onChange
}: {
  checked: boolean
  onChange: (value: boolean) => void
}): ReactElement {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
        checked ? 'bg-accent' : 'bg-ds-border'
      }`}
    >
      <span
        className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
          checked ? 'translate-x-5' : 'translate-x-0'
        }`}
      />
    </button>
  )
}
