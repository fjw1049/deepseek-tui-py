import { useCallback, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'

type ApprovalBlock = Extract<ChatBlock, { kind: 'approval' }>

function isDestructiveApproval(block: ApprovalBlock): boolean {
  return block.presentationRisk === 'destructive' || block.riskLevel === 'high'
}

export function ApprovalBubble({ block }: { block: ApprovalBlock }): ReactElement {
  const { t } = useTranslation('common')
  const resolveApproval = useChatStore((s) => s.resolveApproval)
  const openSettings = useChatStore((s) => s.openSettings)

  const done = block.status !== 'pending'
  const destructive = isDestructiveApproval(block)
  const commandText = block.inputSummary?.trim() || ''
  const reasonText =
    block.summary.trim() &&
    block.summary.trim() !== commandText &&
    !/^tool has \w+ risk level$/i.test(block.summary.trim())
      ? block.summary.trim()
      : block.riskLevel
        ? t('approvalRiskLevel', { level: block.riskLevel })
        : ''
  const statusLabel =
    block.status === 'allowed'
      ? t('approvalAllowed')
      : block.status === 'denied'
        ? t('approvalDenied')
        : block.status === 'error'
          ? t('approvalFailed')
          : t('approvalPending')

  const submitAllow = useCallback(
    (remember: boolean) => {
      void resolveApproval(block.id, 'allow', remember)
    },
    [block.id, resolveApproval]
  )

  return (
    <div
      id={`block-${block.id}`}
      className={`rounded-[14px] border px-4 py-4 text-[13px] leading-6 shadow-[0_12px_30px_rgba(86,103,136,0.04)] ${
        block.status === 'error'
          ? 'border-red-300/80 bg-red-500/10 dark:border-red-800/60 dark:bg-red-950/35'
          : 'border-accent/35 bg-[linear-gradient(180deg,rgba(79,124,255,0.08),rgba(79,124,255,0.12))] text-ds-ink'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <div className="font-semibold text-accent">{t('approvalTitle')}</div>
        {destructive ? (
          <span className="rounded-md bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-800 dark:text-amber-200">
            {t('approvalDestructive')}
          </span>
        ) : null}
      </div>
      {block.toolName ? (
        <div className="mt-1 text-[12px] text-ds-muted">
          {t('approvalTool', { name: block.toolName })}
        </div>
      ) : null}
      {block.impacts && block.impacts.length > 0 ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px] text-ds-ink">
          {block.impacts.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}
      {commandText ? (
        <div className="mt-3">
          <div className="text-[11px] font-medium uppercase tracking-[0.12em] text-ds-faint">
            {t('approvalCommand')}
          </div>
          <pre className="mt-1.5 overflow-x-auto whitespace-pre-wrap break-words rounded-xl border border-ds-border-muted bg-ds-main/80 px-3 py-2.5 font-mono text-[13px] leading-6 text-ds-ink">
            {commandText}
          </pre>
        </div>
      ) : (
        <p className="mt-2 whitespace-pre-wrap text-[14px] text-ds-ink">{block.summary}</p>
      )}
      {reasonText ? <p className="mt-2 text-[12px] text-ds-muted">{reasonText}</p> : null}
      {block.status === 'pending' ? (
        <p className="mt-2 text-[12px] text-ds-muted">{t('approvalPolicyHint')}</p>
      ) : null}
      {block.errorMessage ? (
        <p className="mt-2 text-[12px] text-red-700 dark:text-red-300">{block.errorMessage}</p>
      ) : null}
      {!done ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            className="rounded-lg bg-emerald-600 px-3 py-1.5 text-[13px] font-medium text-white hover:bg-emerald-700"
            onClick={() => submitAllow(false)}
          >
            {t('approvalAllow')}
          </button>
          <button
            type="button"
            className="rounded-lg bg-emerald-700/90 px-3 py-1.5 text-[13px] font-medium text-white hover:bg-emerald-800"
            onClick={() => submitAllow(true)}
          >
            {t('approvalAllowRemember')}
          </button>
          <button
            type="button"
            className="rounded-lg border border-ds-border bg-ds-card px-3 py-1.5 text-[13px] font-medium text-ds-ink hover:bg-ds-hover"
            onClick={() => {
              void resolveApproval(block.id, 'deny')
            }}
          >
            {t('approvalDeny')}
          </button>
          <button
            type="button"
            className="rounded-lg px-3 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
            onClick={() => openSettings('permissions')}
          >
            {t('approvalOpenSettings')}
          </button>
        </div>
      ) : (
        <p className="mt-2 text-[12px] font-medium text-ds-muted">{statusLabel}</p>
      )}
    </div>
  )
}
