import { useCallback, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'

type ElevationBlock = Extract<ChatBlock, { kind: 'elevation' }>

export function ElevationBubble({ block }: { block: ElevationBlock }): ReactElement {
  const { t } = useTranslation('common')
  const resolveElevation = useChatStore((s) => s.resolveElevation)

  const done = block.status !== 'pending'
  const statusLabel =
    block.status === 'allowed'
      ? t('elevationAllowed')
      : block.status === 'denied'
        ? t('elevationDenied')
        : block.status === 'error'
          ? t('elevationFailed')
          : t('elevationPending')

  const onAllow = useCallback(() => {
    void resolveElevation(block.id, 'allow')
  }, [block.id, resolveElevation])

  const onDeny = useCallback(() => {
    void resolveElevation(block.id, 'deny')
  }, [block.id, resolveElevation])

  return (
    <div
      id={`block-${block.id}`}
      className="ds-elevation-bubble rounded-2xl border border-ds-border bg-ds-card px-3.5 py-3 text-[13px] leading-6 text-ds-ink shadow-panel"
    >
      <div className="flex items-center gap-2">
        <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-accent" />
        <span className="font-semibold tracking-[-0.01em] text-ds-ink">{t('elevationTitle')}</span>
        {block.toolName ? (
          <span className="rounded-md bg-ds-subtle px-1.5 py-0.5 font-mono text-[11px] text-ds-muted">
            {block.toolName}
          </span>
        ) : null}
      </div>
      <p className="mt-2 text-ds-ink">{block.reason}</p>
      <div className="mt-1 text-[11px] text-ds-faint">
        {t('elevationKind', { kind: block.elevationKind })}
      </div>
      {block.commandPreview ? (
        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words rounded-xl bg-ds-subtle px-3 py-2.5 font-mono text-[12.5px] leading-6 text-ds-ink">
          {block.commandPreview}
        </pre>
      ) : null}
      {!done ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-ds-border-muted pt-2.5">
          <button
            type="button"
            className="rounded-[10px] bg-accent px-3.5 py-1.5 text-[13px] font-medium text-white shadow-sm transition hover:brightness-[1.06] active:brightness-95"
            onClick={onAllow}
          >
            {t('elevationAllowOnce')}
          </button>
          <button
            type="button"
            className="rounded-[10px] px-3 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
            onClick={onDeny}
          >
            {t('elevationDeny')}
          </button>
        </div>
      ) : (
        <div className="mt-2 text-[12px] font-medium text-ds-muted">{statusLabel}</div>
      )}
      {block.errorMessage ? (
        <div className="mt-2 text-[12px] text-ds-danger">{block.errorMessage}</div>
      ) : null}
    </div>
  )
}
