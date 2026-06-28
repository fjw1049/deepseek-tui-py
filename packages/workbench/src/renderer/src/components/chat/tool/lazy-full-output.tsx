import { useCallback, useEffect, useState } from 'react'
import { useChatStore } from '../../../store/chat-store'
import { getProvider } from '../../../agent/registry'
import { useTranslation } from 'react-i18next'

/**
 * Lazy-loaded full tool detail. Shown only when a tool's `detail` was truncated
 * by the runtime and the user expands the card. Mirrors the legacy
 * `useFullToolDetail` / `LazyToolDetail` behaviour but lives inside the tool
 * layer so the card host stays declarative.
 */
const FULL_OUTPUT_RENDER_MAX_CHARS = 200_000

export function LazyFullOutput({
  text,
  itemId
}: {
  text: string
  itemId: string
}): React.JSX.Element {
  const { t } = useTranslation('common')
  const [state, setState] = useState<{ loading: boolean; detail: string | null }>({
    loading: false,
    detail: null
  })

  const expand = useCallback((): void => {
    if (state.loading || state.detail !== null) return
    const providerId = useChatStore.getState().providerId
    const provider = getProvider(providerId)
    if (typeof provider.fetchItemDetail !== 'function') return
    setState({ loading: true, detail: null })
    void provider
      .fetchItemDetail(itemId)
      .then((result) => setState({ loading: false, detail: result.detail ?? '' }))
      .catch(() => setState({ loading: false, detail: '' }))
  }, [itemId, state.detail, state.loading])

  useEffect(() => {
    setState({ loading: false, detail: null })
  }, [itemId])

  const raw = state.detail !== null ? state.detail : text
  // Even the lazily-fetched full detail can be multiple megabytes (e.g. a tool
  // that dumped a whole file). Rendering that into one <pre> locks up the render
  // thread, so we hard-cap what actually reaches the DOM and tell the user.
  const overLimit = raw.length > FULL_OUTPUT_RENDER_MAX_CHARS
  const display = overLimit ? raw.slice(0, FULL_OUTPUT_RENDER_MAX_CHARS) : raw
  return (
    <div className="relative">
      <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[12px] leading-6 text-ds-ink">
        {display}
      </pre>
      {overLimit ? (
        <div className="mt-1 text-[11px] text-ds-muted">
          {t('toolOutputTruncatedNotice', {
            shown: FULL_OUTPUT_RENDER_MAX_CHARS.toLocaleString(),
            total: raw.length.toLocaleString()
          })}
        </div>
      ) : null}
      {state.detail === null ? (
        <button
          type="button"
          onClick={expand}
          disabled={state.loading}
          className="absolute bottom-1 right-1 rounded-md border border-ds-border-muted bg-ds-card/90 px-2 py-0.5 text-[11px] text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
        >
          {state.loading ? '…' : t('toolDetailExpandFull')}
        </button>
      ) : null}
    </div>
  )
}

export default LazyFullOutput
