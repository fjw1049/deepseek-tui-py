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
      className="rounded-[14px] border border-amber-400/40 bg-[linear-gradient(180deg,rgba(251,191,36,0.08),rgba(251,191,36,0.14))] px-4 py-4 text-[13px] leading-6 text-ds-ink shadow-[0_12px_30px_rgba(86,103,136,0.04)]"
    >
      <div className="font-semibold text-amber-800 dark:text-amber-200">{t('elevationTitle')}</div>
      {block.toolName ? (
        <div className="mt-1 text-[12px] text-ds-muted">
          {t('approvalTool', { name: block.toolName })}
        </div>
      ) : null}
      <p className="mt-2 text-ds-ink">{block.reason}</p>
      <div className="mt-1 text-[11px] uppercase tracking-[0.12em] text-ds-faint">
        {t('elevationKind', { kind: block.elevationKind })}
      </div>
      {block.commandPreview ? (
        <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words rounded-xl border border-ds-border-muted bg-ds-main/80 px-3 py-2.5 font-mono text-[12px] leading-6">
          {block.commandPreview}
        </pre>
      ) : null}
      {!done ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            className="ds-btn-primary rounded-full px-4 py-1.5 text-[12px] font-semibold"
            onClick={onAllow}
          >
            {t('elevationAllowOnce')}
          </button>
          <button
            type="button"
            className="ds-btn-ghost rounded-full px-4 py-1.5 text-[12px]"
            onClick={onDeny}
          >
            {t('elevationDeny')}
          </button>
        </div>
      ) : (
        <div className="mt-2 text-[12px] font-medium text-ds-muted">{statusLabel}</div>
      )}
      {block.errorMessage ? (
        <div className="mt-2 text-[12px] text-red-600 dark:text-red-300">{block.errorMessage}</div>
      ) : null}
    </div>
  )
}
