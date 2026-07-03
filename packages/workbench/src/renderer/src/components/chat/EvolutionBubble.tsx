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
      className={`rounded-[14px] border px-4 py-4 text-[13px] leading-6 shadow-[0_12px_30px_rgba(86,103,136,0.04)] ${
        block.status === 'error'
          ? 'border-red-300/80 bg-red-500/10 dark:border-red-800/60 dark:bg-red-950/35'
          : 'border-violet-300/50 bg-[linear-gradient(180deg,rgba(139,92,246,0.08),rgba(139,92,246,0.12))] text-ds-ink dark:border-violet-800/50'
      }`}
    >
      <div className="font-semibold text-violet-700 dark:text-violet-300">{t('evolutionTitle')}</div>
      {block.kindLabel ? (
        <div className="mt-1 text-[12px] text-ds-muted">{t('evolutionKind', { kind: block.kindLabel })}</div>
      ) : null}
      <p className="mt-2 whitespace-pre-wrap text-[14px] text-ds-ink">{block.summary}</p>
      {block.assetPath ? (
        <div className="mt-2 text-[12px] text-ds-muted">{block.assetPath}</div>
      ) : null}
      {block.status === 'pending' ? (
        <p className="mt-2 text-[12px] text-ds-muted">{t('evolutionPolicyHint')}</p>
      ) : null}
      {block.errorMessage ? (
        <p className="mt-2 text-[12px] text-red-700 dark:text-red-300">{block.errorMessage}</p>
      ) : null}
      {!done ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded-lg bg-emerald-600 px-3 py-1.5 text-[13px] font-medium text-white hover:bg-emerald-700"
            onClick={() => void resolveEvolution(block.id, 'approve')}
          >
            {t('evolutionApprove')}
          </button>
          <button
            type="button"
            className="rounded-lg border border-ds-border bg-ds-card px-3 py-1.5 text-[13px] font-medium text-ds-ink hover:bg-ds-hover"
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
