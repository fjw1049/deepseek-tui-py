import { DEFAULT_COMPOSER_MODEL_IDS } from '@shared/default-composer-models'

/** Short label for the composer model chip (e.g. deepseek-v4-pro → v4-pro). */
export function formatComposerModelLabel(modelId: string): string {
  const id = modelId.trim()
  if (!id) return ''
  if (id === 'deepseek-v4-pro') return 'v4-pro'
  if (id === 'deepseek-v4-flash') return 'v4-flash'
  if (id.startsWith('deepseek-')) return id.slice('deepseek-'.length)
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
