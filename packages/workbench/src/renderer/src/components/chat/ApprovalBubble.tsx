import { useCallback, useEffect, useMemo, useState, type ReactElement, type ReactNode } from 'react'
import { Check, ChevronDown, CircleAlert, LoaderCircle, ShieldCheck, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'

type ApprovalBlock = Extract<ChatBlock, { kind: 'approval' }>

type ApprovalVisualStatus = 'pending' | 'approving' | 'allowed' | 'denied' | 'error'

function isDestructiveApproval(block: ApprovalBlock): boolean {
  return block.presentationRisk === 'destructive' || block.riskLevel === 'high'
}

function looksLikeShellTool(toolName: string | undefined, commandText: string): boolean {
  if (commandText) return true
  const name = (toolName || '').toLowerCase()
  return name.includes('shell') || name.includes('terminal') || name.includes('bash')
}

/** Drop boilerplate / command echoes already shown in the command row. */
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

function splitImpactLine(line: string): { label: string; value: string } {
  const match = line.match(/^([^:]{1,32}):\s*(.+)$/)
  if (match) return { label: match[1], value: match[2] }
  return { label: '', value: line }
}

function statusBadgeClass(status: ApprovalVisualStatus): string {
  if (status === 'pending') {
    return 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400'
  }
  if (status === 'approving') {
    return 'border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-400'
  }
  if (status === 'allowed') {
    return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400'
  }
  return 'border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-400'
}

function StatusIcon({
  status,
  destructive
}: {
  status: ApprovalVisualStatus
  destructive: boolean
}): ReactElement {
  if (status === 'approving') {
    return <LoaderCircle className="size-4 animate-spin" strokeWidth={2} />
  }
  if (status === 'error') {
    return <CircleAlert className="size-4" strokeWidth={2} />
  }
  if (status === 'denied') {
    return <X className="size-4" strokeWidth={2} />
  }
  if (status === 'allowed') {
    return <Check className="size-4" strokeWidth={2} />
  }
  return (
    <ShieldCheck
      className={`size-4 ${destructive ? 'text-ds-danger' : ''}`}
      strokeWidth={2}
    />
  )
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
  const shellLike = looksLikeShellTool(block.toolName, commandText)
  const metaLines = useMemo(
    () => usefulImpactLines(block.impacts, commandText),
    [block.impacts, commandText]
  )
  const parameters = useMemo(() => {
    const rows: { id: string; label: string; value: ReactNode }[] = []
    if (commandText) {
      rows.push({
        id: 'command',
        label: t('approvalCommand'),
        value: (
          <pre className="m-0 overflow-x-auto whitespace-pre-wrap break-words rounded-lg border border-ds-border bg-ds-card px-2.5 py-2 font-mono text-[12px] leading-5 text-ds-ink">
            <span aria-hidden className="select-none text-ds-faint">
              ❯{' '}
            </span>
            {commandText}
          </pre>
        )
      })
    }
    metaLines.forEach((line, index) => {
      const split = splitImpactLine(line)
      rows.push({
        id: `impact-${index}`,
        label: split.label || t('approvalImpact'),
        value: split.value
      })
    })
    return rows
  }, [commandText, metaLines, t])

  const [detailsOpen, setDetailsOpen] = useState(shellLike)
  useEffect(() => {
    if (done) setDetailsOpen(false)
  }, [done])

  const visualStatus: ApprovalVisualStatus = submitting
    ? 'approving'
    : block.status === 'pending'
      ? 'pending'
      : block.status

  const title =
    visualStatus === 'pending'
      ? t('approvalAskTitle')
      : block.toolName || t('approvalTitle')

  const statusLabel =
    visualStatus === 'approving'
      ? t('approvalApproving')
      : visualStatus === 'allowed'
        ? t('approvalAllowed')
        : visualStatus === 'denied'
          ? t('approvalDenied')
          : visualStatus === 'error'
            ? t('approvalFailed')
            : t('approvalTitle')

  const submit = useCallback(
    (decision: 'allow' | 'deny', remember = false) => {
      if (busy) return
      setSubmitting(true)
      void resolveApproval(block.id, decision, remember).then((started) => {
        if (!started) setSubmitting(false)
      })
    },
    [block.id, busy, resolveApproval]
  )

  return (
    <div
      id={`block-${block.id}`}
      data-state={visualStatus}
      aria-busy={visualStatus === 'approving'}
      className={`ds-approval-bubble w-full overflow-hidden rounded-2xl border text-[13px] leading-5 ${
        block.status === 'error'
          ? 'border-rose-500/25 bg-ds-danger-soft text-ds-ink'
          : 'border-ds-border bg-ds-subtle text-ds-ink'
      }`}
    >
      <div className="flex items-start gap-3 px-4 pt-3.5">
        <span
          aria-hidden
          className={`mt-0.5 grid size-8 shrink-0 place-items-center rounded-xl border border-ds-border bg-ds-card text-ds-muted ${
            visualStatus === 'error' || (destructive && visualStatus === 'pending')
              ? 'text-ds-danger'
              : visualStatus === 'allowed'
                ? 'text-emerald-600 dark:text-emerald-400'
                : visualStatus === 'denied'
                  ? 'text-rose-600 dark:text-rose-400'
                  : ''
          }`}
        >
          <StatusIcon status={visualStatus} destructive={destructive} />
        </span>

        <div className="min-w-0 flex-1 pb-3.5">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="font-semibold tracking-[-0.02em] text-ds-ink">{title}</span>
            {block.toolName ? (
              <span className="rounded-md bg-ds-card px-1.5 py-0.5 font-mono text-[11px] leading-4 text-ds-muted">
                {block.toolName}
              </span>
            ) : null}
            {block.taskId ? (
              <span className="truncate font-mono text-[11px] text-ds-faint">
                {t('userInputFromTask', { id: block.taskId })}
              </span>
            ) : null}
            <span
              className={`shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium ${statusBadgeClass(visualStatus)}`}
            >
              {statusLabel}
            </span>
            {destructive && visualStatus === 'pending' ? (
              <span className="text-[11px] font-medium text-ds-danger">
                {t('approvalDestructive')}
              </span>
            ) : null}
          </div>

          {block.summary && !commandText ? (
            <p className="mt-1.5 whitespace-pre-wrap text-[13px] leading-5 text-ds-muted">
              {block.summary}
            </p>
          ) : visualStatus === 'pending' ? (
            <p className="mt-1.5 text-[12px] leading-5 text-ds-muted">{t('approvalPolicyHint')}</p>
          ) : null}

          {parameters.length > 0 ? (
            <button
              type="button"
              aria-expanded={detailsOpen}
              onClick={() => setDetailsOpen((open) => !open)}
              className="mt-2 inline-flex items-center gap-1 rounded-md text-[12px] font-medium text-ds-muted outline-none transition-colors hover:text-ds-ink"
            >
              {t('approvalViewDetails')}
              <ChevronDown
                aria-hidden
                className={`size-3.5 transition-transform ${detailsOpen ? 'rotate-180' : ''}`}
                strokeWidth={2}
              />
            </button>
          ) : null}

          {block.errorMessage ? (
            <p className="mt-2 text-[12px] text-ds-danger">{block.errorMessage}</p>
          ) : null}
        </div>
      </div>

      {detailsOpen && parameters.length > 0 ? (
        <div className="space-y-2 border-t border-ds-border px-4 py-3">
          {parameters.map((parameter) => (
            <div
              key={parameter.id}
              className="grid grid-cols-[minmax(0,6.5rem)_minmax(0,1fr)] items-start gap-3 text-[12px]"
            >
              <span className="pt-1.5 text-ds-muted">{parameter.label}</span>
              <div className="min-w-0 text-ds-ink">{parameter.value}</div>
            </div>
          ))}
        </div>
      ) : null}

      {visualStatus === 'pending' ? (
        <div className="flex flex-wrap items-center gap-1.5 border-t border-ds-border px-4 py-3">
          <button
            type="button"
            disabled={busy}
            className="rounded-xl bg-ds-ink px-3 py-1.5 text-[12px] font-medium text-ds-canvas transition active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50"
            onClick={() => submit('allow', false)}
          >
            {t('approvalAllowOnce')}
          </button>
          <button
            type="button"
            disabled={busy}
            className="rounded-xl border border-ds-border bg-ds-card px-3 py-1.5 text-[12px] font-medium text-ds-ink transition hover:bg-ds-hover active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50"
            onClick={() => submit('allow', true)}
          >
            {t('approvalAllowRemember')}
          </button>
          <button
            type="button"
            disabled={busy}
            className={`rounded-xl px-3 py-1.5 text-[12px] font-medium transition hover:bg-ds-hover disabled:pointer-events-none disabled:opacity-50 ${
              destructive ? 'text-ds-danger' : 'text-ds-muted hover:text-ds-ink'
            }`}
            onClick={() => submit('deny')}
          >
            {t('approvalDeny')}
          </button>
          <button
            type="button"
            className="rounded-xl px-3 py-1.5 text-[12px] font-medium text-ds-faint transition hover:bg-ds-hover hover:text-ds-muted"
            onClick={() => openSettings('permissions')}
          >
            {t('approvalOpenSettings')}
          </button>
        </div>
      ) : null}
    </div>
  )
}
