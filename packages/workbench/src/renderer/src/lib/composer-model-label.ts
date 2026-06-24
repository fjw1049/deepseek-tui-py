import { DEFAULT_COMPOSER_MODEL_IDS } from '@shared/default-composer-models'
import { decodeModelRef } from '@shared/model-ref'

/** Provider display name + optional model label for custom-endpoint models. */
export type ComposerModelMeta = {
  endpointName: string
  label?: string
}

/**
 * Short label for the composer model chip.
 *
 * Built-in DeepSeek models show as ``deepseek/v4-pro`` (the ``deepseek-``
 * prefix on the wire id is stripped so we don't render ``deepseek/deepseek-v4-pro``).
 * Custom-endpoint models show as ``<endpointName>/<modelLabel|modelId>``, e.g.
 * ``青云/claude-opus-4-6`` or ``青云/我的Opus`` when a label is set.
 *
 * ``metaMap`` is optional so callers without endpoint metadata (e.g. the ``/model``
 * command panel before store hydration) still get a readable label — they fall
 * back to the raw provider id.
 */
export function formatComposerModelLabel(
  modelId: string,
  metaMap?: Record<string, ComposerModelMeta>
): string {
  const ref = decodeModelRef(modelId)
  const id = ref.modelId
  if (!id) return ''
  if (ref.providerId === 'deepseek') {
    const stripped = id.startsWith('deepseek-') ? id.slice('deepseek-'.length) : id
    return `deepseek/${stripped}`
  }
  const meta = metaMap?.[modelId]
  const displayId = meta?.label?.trim() || id
  const providerName = meta?.endpointName?.trim() || ref.providerId
  return `${providerName}/${displayId}`
}

/** Model id only — no provider prefix — for compact usage stats. */
export function formatUsageModelName(
  modelId: string,
  metaMap?: Record<string, ComposerModelMeta>
): string {
  const ref = decodeModelRef(modelId)
  const id = ref.modelId
  if (!id) return ''
  const meta = metaMap?.[modelId]
  if (meta?.label?.trim()) return meta.label.trim()
  if (ref.providerId === 'deepseek' && id.startsWith('deepseek-')) {
    return id.slice('deepseek-'.length)
  }
  return id
}

export function filterComposerModelOptions(
  composerModel: string,
  composerPickList: string[]
): string[] {
  const ordered = new Set<string>(DEFAULT_COMPOSER_MODEL_IDS)
  if (composerModel.trim()) ordered.add(composerModel.trim())
  for (const id of composerPickList) {
    const trimmed = id.trim()
    if (trimmed && trimmed !== 'auto') ordered.add(trimmed)
  }
  const preferred = new Set<string>(DEFAULT_COMPOSER_MODEL_IDS)
  const tail = [...ordered].filter((id) => !preferred.has(id)).sort((a, b) => a.localeCompare(b))
  return [...DEFAULT_COMPOSER_MODEL_IDS, ...tail]
}
