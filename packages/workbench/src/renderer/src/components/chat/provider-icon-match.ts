export type ProviderIconBrand =
  | 'claude'
  | 'codex'
  | 'gemini'
  | 'grok'
  | 'deepseek'
  | 'glm'
  | 'kimi'
  | 'qwen'
  | 'minimax'
  | 'doubao'
  | 'unknown'

/**
 * Extract the model token used for brand matching.
 * Never include custom-endpoint name/id — an endpoint named "zhipu" must not
 * force every zhipu/<model> row to the GLM icon.
 */
export function modelIconMatchText(parts: {
  providerId?: string
  id?: string
  label?: string
} = {}): string {
  const wireId = String(parts.id || '')
  const modelPart = wireId.includes('::') ? wireId.slice(wireId.indexOf('::') + 2) : wireId
  const label = String(parts.label || '')
  // Labels render as "<endpointName>/<model>"; only the trailing model matters.
  const labelModel = label.includes('/') ? label.slice(label.lastIndexOf('/') + 1) : label
  return [modelPart, labelModel]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

export function resolveProviderIconBrand(parts: {
  providerId?: string
  id?: string
  label?: string
} = {}): ProviderIconBrand {
  const hay = modelIconMatchText(parts)
  const wireId = String(parts.id || '')
  const modelPart = wireId.includes('::') ? wireId.slice(wireId.indexOf('::') + 2) : wireId

  if (/(claude|anthropic)/.test(hay)) return 'claude'
  if (/(codex|openai|\bgpt[-_.\d]|o[1-4][-_.]|\bchatgpt\b)/.test(hay)) return 'codex'
  if (/(gemini|google)/.test(hay)) return 'gemini'
  if (/(grok|\bxai\b)/.test(hay)) return 'grok'
  if (/(deepseek)/.test(hay)) return 'deepseek'
  if (/(glm|zhipu|chatglm|\bzai\b|\bz\.ai\b|智谱|清言)/.test(hay)) return 'glm'
  if (/(kimi|moonshot|月之暗面|moonshotai)/.test(hay)) return 'kimi'
  if (/(qwen|qwq|通义|千问|dashscope)/.test(hay)) return 'qwen'
  if (/(minimax|海螺|\babab[-_.]|minimaxi)/.test(hay)) return 'minimax'
  if (/(doubao|豆包)/.test(hay)) return 'doubao'

  const provider = String(parts.providerId || '').toLowerCase()
  if (!hay || provider === 'deepseek' || modelPart.startsWith('deepseek')) {
    return 'deepseek'
  }

  return 'unknown'
}
