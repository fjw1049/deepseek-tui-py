import { type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'

type EvolutionBlock = Extract<ChatBlock, { kind: 'evolution' }>

export function EvolutionBubble({ block }: { block: EvolutionBlock }): ReactElement {
  const { t } = useTranslation('common')
  const resolveEvolution = useChatStore((s) => s.resolveEvolution)

  const done = block.status !== 'pending'
  const statusLabel =
    block.status === 'approved'
      ? t('evolutionApproved')
      : block.status === 'rejected'
        ? t('evolutionRejected')
        : block.status === 'error'
          ? t('evolutionFailed')
          : t('evolutionPending')

  return (
    <div
      id={`block-${block.id}`}
      className={`ds-evolution-bubble rounded-2xl border px-3.5 py-3 text-[13px] leading-6 shadow-panel ${
        block.status === 'error'
          ? 'border-ds-danger/25 bg-ds-danger-soft text-ds-ink'
          : 'border-ds-border bg-ds-card text-ds-ink'
      }`}
    >
      <div className="flex items-center gap-2">
        <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-accent" />
        <span className="font-semibold tracking-[-0.01em] text-ds-ink">{t('evolutionTitle')}</span>
        {block.kindLabel ? (
          <span className="rounded-md bg-ds-subtle px-1.5 py-0.5 text-[11px] text-ds-muted">
            {t('evolutionKind', { kind: block.kindLabel })}
          </span>
        ) : null}
      </div>
      <p className="mt-2 whitespace-pre-wrap text-[14px] text-ds-ink">{block.summary}</p>
      {block.assetPath ? (
        <div className="mt-2 font-mono text-[12px] text-ds-muted">{block.assetPath}</div>
      ) : null}
      {block.errorMessage ? (
        <p className="mt-2 text-[12px] text-ds-danger">{block.errorMessage}</p>
      ) : null}
      {!done ? (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-ds-border-muted pt-2.5">
          <button
            type="button"
            className="rounded-[10px] bg-accent px-3.5 py-1.5 text-[13px] font-medium text-white shadow-sm transition hover:brightness-[1.06] active:brightness-95"
            onClick={() => void resolveEvolution(block.id, 'approve')}
          >
            {t('evolutionApprove')}
          </button>
          <button
            type="button"
            className="rounded-[10px] px-3 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
            onClick={() => void resolveEvolution(block.id, 'reject')}
          >
            {t('evolutionReject')}
          </button>
        </div>
      ) : (
        <p className="mt-2 text-[12px] font-medium text-ds-muted">{statusLabel}</p>
      )}
    </div>
  )
}
