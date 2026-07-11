import { useEffect, useRef } from 'react'
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
  disabled?: boolean
}

/**
 * React wrapper around the <reasoning-effort-selector> Web Component.
 *
 * The custom element owns its animation (magnetic slider, spring snap, canvas
 * sparkles, Ultra confetti) inside a Shadow DOM and renders both the model list
 * and the effort slider. React only syncs data in/out via attributes + the
 * `change` CustomEvent (detail.type = 'model' | 'effort') - it never touches
 * the shadow tree, so re-renders never disturb an in-flight animation.
 *
 * `models` is a complex type, so it is set as a DOM property (not an
 * attribute). `model`/`value` are strings set as attributes.
 */
export function ReasoningEffortSelector({
  models,
  model,
  onModelChange,
  value,
  onChange,
  disabled,
}: ReasoningEffortSelectorProps) {
  const ref = useRef<HTMLElement>(null)
  const onModelChangeRef = useRef(onModelChange)
  const onChangeRef = useRef(onChange)
  onModelChangeRef.current = onModelChange
  onChangeRef.current = onChange
  const index = EFFORT_TO_INDEX[value] ?? 2

  // models is a complex type -> must be set as a property, not an attribute
  useEffect(() => {
    const el = ref.current
    if (el) el.models = models
  }, [models])

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
      } else if (detail.index != null) {
        onChangeRef.current(INDEX_TO_EFFORT[detail.index] ?? 'high')
      }
    }
    el.addEventListener('change', handler)
    return () => el.removeEventListener('change', handler)
  }, [])

  return <reasoning-effort-selector ref={ref} className="ds-no-drag" value={String(index)} model={model} />
}
