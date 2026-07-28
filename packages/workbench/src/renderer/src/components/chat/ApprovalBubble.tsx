import { useCallback, useState, type ReactElement } from 'react'
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
  const [submitting, setSubmitting] = useState(false)

  const done = block.status !== 'pending'
  const busy = done || submitting
  const destructive = isDestructiveApproval(block)
  const commandText = block.inputSummary?.trim() || ''
  const impacts =
    destructive && block.impacts && block.impacts.length > 0 ? block.impacts : null
  const statusLabel =
    block.status === 'allowed'
      ? t('approvalAllowed')
      : block.status === 'denied'
        ? t('approvalDenied')
        : block.status === 'error'
          ? t('approvalFailed')
          : t('approvalPending')

  const submit = useCallback(
    (decision: 'allow' | 'deny', remember = false) => {
      if (busy) return
      setSubmitting(true)
      void resolveApproval(block.id, decision, remember).then((started) => {
        // Keep disabled until the pending card unmounts; only unlock if this
        // call did not acquire the in-flight lock (duplicate click).
        if (!started) setSubmitting(false)
      })
    },
    [block.id, busy, resolveApproval]
  )

  return (
    <div
      id={`block-${block.id}`}
      className={`rounded-2xl border px-4 py-3.5 text-[13px] leading-6 shadow-panel ${
        block.status === 'error'
          ? 'border-ds-danger/25 bg-ds-danger-soft text-ds-ink'
          : 'border-ds-border bg-ds-card text-ds-ink'
      }`}
    >
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          className={`h-2 w-2 shrink-0 rounded-full ${
            block.status === 'error' || destructive ? 'bg-ds-danger' : 'bg-accent'
          }`}
        />
        <span className="font-semibold tracking-[-0.01em] text-ds-ink">{t('approvalTitle')}</span>
        {block.toolName ? (
          <span className="rounded-md bg-ds-subtle px-1.5 py-0.5 font-mono text-[11px] text-ds-muted">
            {block.toolName}
          </span>
        ) : null}
        {destructive ? (
          <span className="text-[11px] font-medium text-ds-danger">{t('approvalDestructive')}</span>
        ) : null}
      </div>

      {commandText ? (
        <div className="mt-2.5 flex items-center gap-2.5 rounded-xl bg-ds-subtle py-1.5 pl-3 pr-1.5">
          <span aria-hidden className="shrink-0 font-mono text-[13px] text-ds-faint">
            ❯
          </span>
          <pre className="min-w-0 flex-1 overflow-x-auto whitespace-pre-wrap break-words font-mono text-[12.5px] leading-6 text-ds-ink">
            {commandText}
          </pre>
          {!done ? (
            <button
              type="button"
              disabled={busy}
              className="shrink-0 self-center rounded-[9px] bg-accent px-3.5 py-1.5 text-[13px] font-medium text-white shadow-sm transition hover:brightness-[1.06] active:brightness-95 disabled:pointer-events-none disabled:opacity-50"
              onClick={() => submit('allow', false)}
            >
              {t('approvalAllow')}
            </button>
          ) : null}
        </div>
      ) : (
        <p className="mt-2 whitespace-pre-wrap text-[14px] text-ds-ink">{block.summary}</p>
      )}

      {impacts ? (
        <ul className="mt-2 list-disc space-y-1 pl-5 text-[12.5px] text-ds-muted">
          {impacts.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}

      {block.errorMessage ? (
        <p className="mt-2 text-[12px] text-ds-danger">{block.errorMessage}</p>
      ) : null}

      {!done ? (
        <div className="mt-2.5 flex flex-wrap items-center gap-2 border-t border-ds-border-muted pt-2.5">
          {!commandText ? (
            <button
              type="button"
              disabled={busy}
              className="rounded-[10px] bg-accent px-3.5 py-1.5 text-[13px] font-medium text-white shadow-sm transition hover:brightness-[1.06] active:brightness-95 disabled:pointer-events-none disabled:opacity-50"
              onClick={() => submit('allow', false)}
            >
              {t('approvalAllow')}
            </button>
          ) : null}
          <button
            type="button"
            disabled={busy}
            className="rounded-[10px] bg-accent-soft px-3 py-1.5 text-[13px] font-medium text-accent transition hover:brightness-[0.97] disabled:pointer-events-none disabled:opacity-50"
            onClick={() => submit('allow', true)}
          >
            {t('approvalAllowRemember')}
          </button>
          <button
            type="button"
            disabled={busy}
            className={`rounded-[10px] px-3 py-1.5 text-[13px] font-medium transition hover:bg-ds-hover disabled:pointer-events-none disabled:opacity-50 ${
              destructive ? 'text-ds-danger' : 'text-ds-muted'
            }`}
            onClick={() => submit('deny')}
          >
            {t('approvalDeny')}
          </button>
          <button
            type="button"
            className="ml-auto rounded-[10px] px-2.5 py-1.5 text-[12px] font-medium text-ds-faint transition hover:bg-ds-hover hover:text-ds-muted"
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
