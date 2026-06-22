export const BUILTIN_DEEPSEEK_PROVIDER_ID = 'deepseek'
const SEPARATOR = '::'

export type ModelRef = {
  providerId: string
  modelId: string
}

export function encodeModelRef(providerId: string, modelId: string): string {
  const provider = providerId.trim() || BUILTIN_DEEPSEEK_PROVIDER_ID
  const model = modelId.trim()
  return provider === BUILTIN_DEEPSEEK_PROVIDER_ID
    ? model
    : `${provider}${SEPARATOR}${model}`
}

export function decodeModelRef(value: string): ModelRef {
  const trimmed = value.trim()
  const separatorIndex = trimmed.indexOf(SEPARATOR)
  if (separatorIndex <= 0) {
    return { providerId: BUILTIN_DEEPSEEK_PROVIDER_ID, modelId: trimmed }
  }
  return {
    providerId: trimmed.slice(0, separatorIndex),
    modelId: trimmed.slice(separatorIndex + SEPARATOR.length)
  }
}
