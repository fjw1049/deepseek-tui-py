import { useCallback, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import type { ApprovalGate, ElevationGate } from '../../../lib/tool-gate'
import { useChatStore } from '../../../store/chat-store'

export function ToolGateBar({
  approval,
  elevation
}: {
  approval: ApprovalGate | null
  elevation: ElevationGate | null
}): ReactElement | null {
  if (!approval && !elevation) return null
  return (
    <div
      className="space-y-2 border-t border-amber-500/25 bg-amber-500/8 px-3 py-2.5"
      onClick={(event) => event.stopPropagation()}
      onKeyDown={(event) => event.stopPropagation()}
    >
      {approval ? <ApprovalActions block={approval} /> : null}
      {elevation ? <ElevationActions block={elevation} /> : null}
    </div>
  )
}

function ApprovalActions({ block }: { block: ApprovalGate }): ReactElement {
  const { t } = useTranslation('common')
  const resolveApproval = useChatStore((s) => s.resolveApproval)
  const [submitting, setSubmitting] = useState(false)

  const submit = useCallback(
    (decision: 'allow' | 'deny', remember = false) => {
      if (submitting) return
      setSubmitting(true)
      void resolveApproval(block.id, decision, remember).then((started) => {
        if (!started) setSubmitting(false)
      })
    },
    [block.id, resolveApproval, submitting]
  )

  return (
    <div>
      <p className="text-[12px] font-medium text-ds-ink">{t('approvalAskTitle')}</p>
      <p className="mt-0.5 text-[11px] leading-5 text-ds-muted">{t('approvalPolicyHint')}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          disabled={submitting}
          className="rounded-xl bg-ds-ink px-3 py-1.5 text-[12px] font-medium text-ds-canvas transition active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50"
          onClick={() => submit('allow', false)}
        >
          {t('approvalAllowOnce')}
        </button>
        <button
          type="button"
          disabled={submitting}
          className="rounded-xl border border-ds-border bg-ds-card px-3 py-1.5 text-[12px] font-medium text-ds-ink transition hover:bg-ds-hover active:scale-[0.97] disabled:pointer-events-none disabled:opacity-50"
          onClick={() => submit('allow', true)}
        >
          {t('approvalAllowRemember')}
        </button>
        <button
          type="button"
          disabled={submitting}
          className="rounded-xl px-3 py-1.5 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:pointer-events-none disabled:opacity-50"
          onClick={() => submit('deny')}
        >
          {t('approvalDeny')}
        </button>
      </div>
    </div>
  )
}

function ElevationActions({ block }: { block: ElevationGate }): ReactElement {
  const { t } = useTranslation('common')
  const resolveElevation = useChatStore((s) => s.resolveElevation)
  const [submitting, setSubmitting] = useState(false)

  return (
    <div>
      <p className="text-[12px] font-medium text-ds-ink">{t('elevationTitle')}</p>
      <p className="mt-0.5 text-[11px] leading-5 text-ds-muted">{block.reason}</p>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          disabled={submitting}
          className="rounded-xl bg-accent px-3 py-1.5 text-[12px] font-medium text-white transition hover:brightness-[1.06] disabled:pointer-events-none disabled:opacity-50"
          onClick={() => {
            if (submitting) return
            setSubmitting(true)
            void resolveElevation(block.id, 'allow')
          }}
        >
          {t('elevationAllowOnce')}
        </button>
        <button
          type="button"
          disabled={submitting}
          className="rounded-xl px-3 py-1.5 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:pointer-events-none disabled:opacity-50"
          onClick={() => {
            if (submitting) return
            setSubmitting(true)
            void resolveElevation(block.id, 'deny')
          }}
        >
          {t('elevationDeny')}
        </button>
      </div>
    </div>
  )
}
