import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { UsageQueryResult, UsageRange } from '@shared/usage-ledger'

export type PersistentUsageState = {
  data: UsageQueryResult | null
  loading: boolean
  loaded: boolean
  error: string | null
}

export function usePersistentUsage(
  range: UsageRange,
  refreshKey: unknown = 0
): PersistentUsageState {
  const { i18n } = useTranslation()
  const [state, setState] = useState<PersistentUsageState>({
    data: null,
    loading: true,
    loaded: false,
    error: null
  })

  useEffect(() => {
    let cancelled = false
    setState((current) => ({ ...current, loading: true, error: null }))
    window.dsGui
      .queryUsage({ range, locale: i18n.language })
      .then((data) => {
        if (!cancelled) {
          setState({ data, loading: false, loaded: true, error: null })
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setState({
            data: null,
            loading: false,
            loaded: true,
            error: caught instanceof Error ? caught.message : String(caught)
          })
        }
      })
    return () => {
      cancelled = true
    }
  }, [range, refreshKey, i18n.language])

  return state
}
