export type ProviderIcon = {
  key: string
  color: string
  svg: string
  colored?: boolean
}

export function uniquifySvgIds(svg: string): string

export function resolveProviderIcon(parts?: {
  providerId?: string
  id?: string
  label?: string
}): ProviderIcon

export function providerIconByKey(key: string): ProviderIcon

export {
  modelIconMatchText,
  resolveProviderIconBrand
} from './provider-icon-match'
