import { useEffect, useMemo, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import './reasoning-effort-selector.js'

const EFFORT_TO_INDEX: Record<string, number> = {
  low: 0,
  medium: 1,
  high: 2,
  xhigh: 3,
  max: 4,
}
const INDEX_TO_EFFORT = ['low', 'medium', 'high', 'xhigh', 'max'] as const

export interface ComposerModelOption {
  id: string
  label: string
  /** Optional provider id for icon coloring (e.g. deepseek, hs). */
  providerId?: string
}

export type ReasoningSelectorLabels = {
  title: string
  hint: string
  warning: string
  aria: string
  desc: string
  configure: string
  dialog: string
}

interface ReasoningEffortSelectorProps {
  /** Selectable models shown in the menu view. */
  models: ComposerModelOption[]
  /** Currently selected model id. */
  model: string
  onModelChange: (id: string) => void
  /** Current reasoning effort (API value: low/medium/high/xhigh/max). */
  value: string
  onChange: (effort: string) => void
  /** Jump to Settings → Models (custom endpoints). */
  onConfigureModels?: () => void
  disabled?: boolean
}

/**
 * React wrapper around the <reasoning-effort-selector> Web Component.
 *
 * Tier names (Light / Medium / High / …) stay English. Other chrome strings
 * come from i18n via the `labels` DOM property.
 */
export function ReasoningEffortSelector({
  models,
  model,
  onModelChange,
  value,
  onChange,
  onConfigureModels,
  disabled,
}: ReasoningEffortSelectorProps) {
  const { t } = useTranslation('common')
  const ref = useRef<HTMLElement>(null)
  const onModelChangeRef = useRef(onModelChange)
  const onChangeRef = useRef(onChange)
  const onConfigureModelsRef = useRef(onConfigureModels)
  onModelChangeRef.current = onModelChange
  onChangeRef.current = onChange
  onConfigureModelsRef.current = onConfigureModels
  const index = EFFORT_TO_INDEX[value] ?? 2

  const labels = useMemo<ReasoningSelectorLabels>(
    () => ({
      title: t('composerReasoningTitle'),
      // Keep English always — short hint reads cleaner than localized copy.
      hint: 'Faster ←→ Smarter',
      warning: t('composerReasoningWarning'),
      aria: t('composerReasoningAria'),
      desc: t('composerReasoningDesc'),
      configure: t('composerConfigureModels'),
      dialog: t('composerModelSettingsAria'),
    }),
    [t]
  )

  useEffect(() => {
    const el = ref.current
    if (el) el.models = models
  }, [models])

  useEffect(() => {
    const el = ref.current
    if (el) el.labels = labels
  }, [labels])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (disabled) el.setAttribute('disabled', '')
    else el.removeAttribute('disabled')
  }, [disabled])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const handler = (e: Event) => {
      const detail = (e as CustomEvent).detail as
        | { type?: string; index?: number; id?: string }
        | undefined
      if (!detail) return
      if (detail.type === 'model' && detail.id != null) {
        onModelChangeRef.current(detail.id)
      } else if (detail.type === 'configure-models') {
        onConfigureModelsRef.current?.()
      } else if (detail.index != null) {
        onChangeRef.current(INDEX_TO_EFFORT[detail.index] ?? 'high')
      }
    }
    el.addEventListener('change', handler)
    return () => el.removeEventListener('change', handler)
  }, [])

  return <reasoning-effort-selector ref={ref} className="ds-no-drag" value={String(index)} model={model} />
}
