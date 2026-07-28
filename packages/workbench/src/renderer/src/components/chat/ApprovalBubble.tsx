import { useCallback, useMemo, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'

type ApprovalBlock = Extract<ChatBlock, { kind: 'approval' }>

function isDestructiveApproval(block: ApprovalBlock): boolean {
  return block.presentationRisk === 'destructive' || block.riskLevel === 'high'
}

/** Drop boilerplate / command echoes already shown in the hero strip. */
function usefulImpactLines(impacts: string[] | undefined, commandText: string): string[] {
  const cmd = commandText.trim()
  const out: string[] = []
  for (const raw of impacts ?? []) {
    const line = raw.trim()
    if (!line) continue
    if (/^(executes a shell command|read-only operation)\.?$/i.test(line)) continue
    if (cmd) {
      const commandPrefixed = line.match(/^command:\s*(.*)$/i)
      if (commandPrefixed) {
        const rest = commandPrefixed[1].trim()
        if (!rest || rest === cmd || cmd.includes(rest) || rest.includes(cmd)) continue
      }
      if (line === cmd) continue
    }
    out.push(line)
  }
  return out
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
  const metaLines = useMemo(
    () => usefulImpactLines(block.impacts, commandText),
    [block.impacts, commandText]
  )
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
      className={`relative overflow-hidden rounded-[18px] border px-4 py-3.5 text-[13px] leading-6 shadow-panel ${
        block.status === 'error'
          ? 'border-ds-danger/25 bg-ds-danger-soft text-ds-ink'
          : 'border-ds-border/80 bg-ds-card/95 text-ds-ink backdrop-blur-xl'
      }`}
    >
      {destructive && block.status !== 'error' ? (
        <span
          aria-hidden
          className="absolute inset-y-3.5 left-0 w-[3px] rounded-full bg-ds-danger/75"
        />
      ) : null}

      <div className={`flex items-start gap-3 ${destructive ? 'pl-1.5' : ''}`}>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-semibold tracking-[-0.02em] text-ds-ink">
              {t('approvalTitle')}
            </span>
            {block.toolName ? (
              <span className="rounded-md bg-ds-subtle px-1.5 py-0.5 font-mono text-[11px] leading-4 text-ds-muted">
                {block.toolName}
              </span>
            ) : null}
            {destructive ? (
              <span className="text-[11px] font-medium tracking-[-0.01em] text-ds-danger">
                {t('approvalDestructive')}
              </span>
            ) : null}
          </div>

          {commandText ? (
            <pre className="mt-2.5 overflow-x-auto whitespace-pre-wrap break-words rounded-[12px] bg-ds-subtle px-3 py-2.5 font-mono text-[12.5px] leading-[1.55] text-ds-ink">
              <span aria-hidden className="select-none text-ds-faint">
                ❯{' '}
              </span>
              {commandText}
            </pre>
          ) : (
            <p className="mt-2 whitespace-pre-wrap text-[14px] leading-6 text-ds-ink">
              {block.summary}
            </p>
          )}

          {metaLines.length > 0 ? (
            <p className="mt-2 text-[12px] leading-5 text-ds-muted">{metaLines.join(' · ')}</p>
          ) : null}

          {block.errorMessage ? (
            <p className="mt-2 text-[12px] text-ds-danger">{block.errorMessage}</p>
          ) : null}
        </div>
      </div>

      {!done ? (
        <div className={`mt-3 flex items-center gap-1.5 ${destructive ? 'pl-1.5' : ''}`}>
          <button
            type="button"
            disabled={busy}
            className={`rounded-[10px] px-2.5 py-1.5 text-[13px] font-medium transition active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50 ${
              destructive
                ? 'text-ds-danger hover:bg-ds-danger-soft'
                : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
            }`}
            onClick={() => submit('deny')}
          >
            {t('approvalDeny')}
          </button>
          <button
            type="button"
            disabled={busy}
            className="rounded-[10px] px-2.5 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50"
            onClick={() => submit('allow', true)}
          >
            {t('approvalAllowRemember')}
          </button>
          <button
            type="button"
            className="rounded-[10px] px-2.5 py-1.5 text-[12px] font-medium text-ds-faint transition hover:bg-ds-hover hover:text-ds-muted"
            onClick={() => openSettings('permissions')}
          >
            {t('approvalOpenSettings')}
          </button>
          <div className="min-w-2 flex-1" />
          <button
            type="button"
            disabled={busy}
            className="rounded-full bg-accent px-4 py-1.5 text-[13px] font-medium text-white shadow-sm transition hover:brightness-[1.06] active:scale-[0.97] active:brightness-95 disabled:pointer-events-none disabled:opacity-50"
            onClick={() => submit('allow', false)}
          >
            {t('approvalAllow')}
          </button>
        </div>
      ) : (
        <p className={`mt-2.5 text-[12px] font-medium text-ds-muted ${destructive ? 'pl-1.5' : ''}`}>
          {statusLabel}
        </p>
      )}
    </div>
  )
}
