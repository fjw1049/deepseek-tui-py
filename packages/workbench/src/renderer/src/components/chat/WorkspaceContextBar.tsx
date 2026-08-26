import { useLayoutEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import { Layers, Laptop } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { getProvider } from '../../agent/registry'
import { isChatsWorkspace, normalizeWorkspaceRoot } from '../../lib/workspace-path'
import {
  workspaceContextBarPlanForWidth,
  workspaceContextBarTierForWidth
} from '../../lib/workspace-context-bar-layout'
import { useChatStore } from '../../store/chat-store'
import { GitBranchPicker } from './GitBranchPicker'
import { ProjectContextPicker } from './ProjectContextPicker'

type Props = {
  workspaceRoot: string
  /** `tray` tucks under the composer card (home + conversation). `embedded` is IDE compact only. */
  variant?: 'tray' | 'embedded'
}

/** Project / Local / worktree / branch row under the composer. */
export function WorkspaceContextBar({ workspaceRoot, variant = 'tray' }: Props): ReactElement {
  const { t } = useTranslation('common')
  const barRef = useRef<HTMLDivElement>(null)
  const [barWidth, setBarWidth] = useState<number | null>(null)
  const [envBusy, setEnvBusy] = useState(false)
  const plan = useMemo(() => workspaceContextBarPlanForWidth(barWidth), [barWidth])
  const tier = workspaceContextBarTierForWidth(barWidth)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const threads = useChatStore((s) => s.threads)
  const busy = useChatStore((s) => s.busy)
  const providerId = useChatStore((s) => s.providerId)
  const setThreadEnvironment = useChatStore((s) => s.setThreadEnvironment)
  const applyWorktree = useChatStore((s) => s.applyWorktree)
  const activeThread = activeThreadId
    ? threads.find((thread) => thread.id === activeThreadId) ?? null
    : null
  const envMode = activeThread?.envMode === 'worktree' ? 'worktree' : 'local'
  const executionRoot =
    envMode === 'worktree' && activeThread?.worktreePath?.trim()
      ? activeThread.worktreePath.trim()
      : workspaceRoot

  useLayoutEffect(() => {
    const el = barRef.current
    if (!el || typeof ResizeObserver === 'undefined') return

    let frame = 0
    const apply = (width: number): void => {
      setBarWidth((prev) => (prev === width ? prev : width))
    }
    apply(el.getBoundingClientRect().width)

    const observer = new ResizeObserver(([entry]) => {
      const nextWidth = entry?.contentRect.width ?? el.getBoundingClientRect().width
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(() => apply(nextWidth))
    })
    observer.observe(el)
    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [])

  const normalizedRoot = normalizeWorkspaceRoot(workspaceRoot)
  const isTemporary = isChatsWorkspace(workspaceRoot) || !normalizedRoot
  const showBranch = Boolean(normalizedRoot) && !isTemporary && plan.showBranch
  const canToggleEnv = Boolean(activeThreadId) && !isTemporary && !busy && !envBusy
  const projectKey = normalizeWorkspaceRoot(activeThread?.workspace || workspaceRoot)
  const siblingCount = projectKey
    ? threads.filter(
        (thread) =>
          thread.id !== activeThreadId &&
          normalizeWorkspaceRoot(thread.workspace) === projectKey
      ).length
    : 0
  const suggestWorktree = envMode === 'local' && siblingCount > 0
  const envLabel = envMode === 'worktree' ? t('contextBarWorktree') : t('contextBarLocal')
  const envHint = envMode === 'worktree'
    ? t('contextBarWorktreeHint')
    : suggestWorktree
      ? t('contextBarWorktreeSuggest')
      : t('contextBarLocalHint')
  const showEnvActions = envMode === 'worktree' && plan.showLocal && canToggleEnv

  const onToggleEnv = async (): Promise<void> => {
    if (!canToggleEnv) return
    const next = envMode === 'worktree' ? 'local' : 'worktree'
    const confirmKey = next === 'worktree' ? 'contextBarHandoffToWorktree' : 'contextBarHandoffToLocal'
    if (!window.confirm(t(confirmKey))) return
    setEnvBusy(true)
    try {
      const ok = await setThreadEnvironment(next)
      if (ok) return
      const err = useChatStore.getState().error || ''
      if (!err.toLowerCase().includes('handoff conflicts')) return
      if (!window.confirm(t('contextBarHandoffConflicts'))) return
      await setThreadEnvironment(next, { forceConflicts: true })
    } finally {
      setEnvBusy(false)
    }
  }

  const onApply = async (): Promise<void> => {
    if (!activeThreadId || busy || envBusy) return
    const provider = getProvider(providerId)
    let summary = t('contextBarApplyConfirm')
    if (typeof provider.previewWorktreeApply === 'function') {
      try {
        const preview = await provider.previewWorktreeApply(activeThreadId)
        const changed = preview.applied.length + preview.merged.length
        const conflicts = preview.conflicted.length
        summary = t('contextBarApplyPreview', { changed, conflicts })
        if (changed === 0 && conflicts === 0) {
          window.alert(t('contextBarApplyEmpty'))
          return
        }
      } catch {
        // Fall through to the generic confirm.
      }
    }
    if (!window.confirm(summary)) return
    setEnvBusy(true)
    try {
      const result = await applyWorktree()
      if (!result) return
      if (result.conflicted.length > 0) {
        const force = window.confirm(
          t('contextBarApplyConflicts', { count: result.conflicted.length })
        )
        if (force) await applyWorktree({ forceConflicts: true })
      }
    } finally {
      setEnvBusy(false)
    }
  }

  const embedded = variant === 'embedded'

  return (
    <div
      ref={barRef}
      className={
        embedded
          ? 'ds-workspace-context-bar ds-workspace-context-bar--embedded relative flex min-h-7 min-w-0 flex-nowrap items-center gap-x-0.5 overflow-hidden px-1 pb-0.5 pt-1'
          : 'ds-workspace-context-bar relative z-0 -mt-5 flex min-h-8 min-w-0 flex-nowrap items-center gap-x-0.5 overflow-hidden rounded-b-[1.2rem] rounded-t-none px-2.5 pb-1.5 pt-6 sm:min-h-7 sm:px-3.5'
      }
      data-workspace-context-bar="true"
      data-context-bar-variant={variant}
      data-context-bar-tier={barWidth == null ? 'unknown' : String(tier)}
    >
      <div className="ds-workspace-context-project min-w-0 shrink">
        <ProjectContextPicker
          workspaceRoot={workspaceRoot}
          usePortal
          menuPlacement="above"
          hideChevron={!plan.showProjectChevron}
        />
      </div>
      {plan.showLocal ? (
        <>
          <span className="ds-workspace-context-sep" aria-hidden />
          {canToggleEnv ? (
            <button
              type="button"
              className="ds-workspace-context-status inline-flex h-7 shrink-0 items-center gap-1 px-1.5"
              title={envHint}
              aria-label={envHint}
              disabled={envBusy}
              onClick={() => {
                void onToggleEnv()
              }}
            >
              {envMode === 'worktree' ? (
                <Layers className="h-3 w-3 shrink-0" strokeWidth={1.7} aria-hidden />
              ) : (
                <Laptop className="h-3 w-3 shrink-0" strokeWidth={1.7} aria-hidden />
              )}
              {plan.showLocalLabel ? <span>{envLabel}</span> : null}
            </button>
          ) : (
            <span
              className="ds-workspace-context-status inline-flex h-7 shrink-0 items-center gap-1 px-1.5"
              title={envHint}
              aria-label={envHint}
            >
              {envMode === 'worktree' ? (
                <Layers className="h-3 w-3 shrink-0" strokeWidth={1.7} aria-hidden />
              ) : (
                <Laptop className="h-3 w-3 shrink-0" strokeWidth={1.7} aria-hidden />
              )}
              {plan.showLocalLabel ? <span>{envLabel}</span> : null}
            </span>
          )}
          {showEnvActions ? (
            <button
              type="button"
              className="ds-workspace-context-status inline-flex h-7 shrink-0 items-center px-1.5"
              title={t('contextBarApplyHint')}
              disabled={envBusy}
              onClick={() => {
                void onApply()
              }}
            >
              {t('contextBarApply')}
            </button>
          ) : null}
        </>
      ) : null}
      {showBranch ? (
        <>
          <span className="ds-workspace-context-sep" aria-hidden />
          <div className="ds-workspace-context-branch min-w-0 shrink">
            <GitBranchPicker
              key={normalizeWorkspaceRoot(executionRoot) || normalizedRoot}
              workspaceRoot={normalizeWorkspaceRoot(executionRoot) || normalizedRoot}
              compact
              usePortal
              menuPlacement="above"
              hideLabel={!plan.showBranchLabel}
              hideChevron={!plan.showBranchChevron}
            />
          </div>
        </>
      ) : null}
    </div>
  )
}
