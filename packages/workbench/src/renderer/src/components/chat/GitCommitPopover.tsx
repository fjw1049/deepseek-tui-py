import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactElement
} from 'react'
import { createPortal } from 'react-dom'
import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  GitCommitHorizontal,
  Loader2,
  MoreHorizontal,
  RefreshCw,
  X
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import type { GitWorkingChangeFile, GitWorkingChangeStage } from '@shared/git-working-changes'
import { countDiffStats, formatFilePathForDisplay } from '../../lib/diff-stats'
import { resolveGitCommitPaths } from '../../lib/git-commit-selection'
import { useChatStore } from '../../store/chat-store'
import { ChangeDiffStatsLabel } from '../ChangeDiffStatsLabel'

type Props = {
  workspaceRoot: string
  currentBranch: string | null
  gitFiles: GitWorkingChangeFile[]
  gitFilesLoading: boolean
  gitDirtyCount: number
  enabled: boolean
  rowClassName: string
  onOpenChanges?: () => void
  onRefreshGit?: () => void
  onCommitted?: () => void
}

function gitStatusLabel(
  status: GitWorkingChangeFile['status'],
  t: (key: string) => string
): string {
  if (status === 'added' || status === 'untracked') return t('gitStatusAdded')
  if (status === 'deleted') return t('gitStatusDeleted')
  if (status === 'renamed') return t('gitStatusRenamed')
  return t('gitStatusModified')
}

function gitStageLabel(stage: GitWorkingChangeStage, t: (key: string) => string): string {
  if (stage === 'staged') return t('gitStageStaged')
  if (stage === 'partial') return t('gitStagePartial')
  return t('gitStageUnstaged')
}

export function GitCommitPopover({
  workspaceRoot,
  currentBranch,
  gitFiles,
  gitFilesLoading,
  gitDirtyCount,
  enabled,
  rowClassName,
  onOpenChanges,
  onRefreshGit,
  onCommitted
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const root = workspaceRoot.trim()
  const [open, setOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [filesExpanded, setFilesExpanded] = useState(true)
  const [message, setMessage] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [generating, setGenerating] = useState(false)
  const dialogRef = useRef<HTMLDivElement | null>(null)
  const anchorRef = useRef<HTMLDivElement | null>(null)
  const endPointerDragRef = useRef<(() => void) | null>(null)
  const [dialogPos, setDialogPos] = useState<{ x: number; y: number } | null>(null)
  const [manualRefreshing, setManualRefreshing] = useState(false)

  const {
    gitCommitSelectionKey,
    gitCommitSelectedPaths,
    toggleGitCommitPath,
    setGitCommitSelectedPaths
  } = useChatStore(
    useShallow((s) => ({
      gitCommitSelectionKey: s.gitCommitSelectionKey,
      gitCommitSelectedPaths: s.gitCommitSelectedPaths,
      toggleGitCommitPath: s.toggleGitCommitPath,
      setGitCommitSelectedPaths: s.setGitCommitSelectedPaths
    }))
  )

  const allPaths = useMemo(() => gitFiles.map((file) => file.path), [gitFiles])
  const onRefreshGitRef = useRef(onRefreshGit)
  onRefreshGitRef.current = onRefreshGit

  useEffect(() => {
    if (!gitFilesLoading) setManualRefreshing(false)
  }, [gitFilesLoading])

  const handleManualRefresh = (): void => {
    setManualRefreshing(true)
    onRefreshGitRef.current?.()
  }

  useEffect(() => {
    setOpen(false)
    setMenuOpen(false)
    setMessage('')
    setError(null)
    setSubmitting(false)
    setGenerating(false)
    setFilesExpanded(true)
    setDialogPos(null)
    setManualRefreshing(false)
  }, [root])

  useEffect(() => {
    return () => {
      endPointerDragRef.current?.()
    }
  }, [])

  useEffect(() => {
    if (!open) endPointerDragRef.current?.()
  }, [open])

  const positionDialogNearAnchor = useCallback((): void => {
    const anchor = anchorRef.current
    const el = dialogRef.current
    const width = el?.offsetWidth ?? 512
    const height = el?.offsetHeight ?? 480
    const margin = 12
    const gap = 8

    if (!anchor) {
      setDialogPos({
        x: Math.max(margin, (window.innerWidth - width) / 2),
        y: Math.max(margin, (window.innerHeight - height) / 2)
      })
      return
    }

    const rect = anchor.getBoundingClientRect()
    let x = rect.right - width
    let y = rect.bottom + gap

    if (y + height > window.innerHeight - margin) {
      const above = rect.top - height - gap
      y = above >= margin ? above : Math.max(margin, window.innerHeight - height - margin)
    }

    x = Math.min(Math.max(margin, x), window.innerWidth - width - margin)
    y = Math.min(Math.max(margin, y), window.innerHeight - height - margin)

    setDialogPos({ x, y })
  }, [])

  useLayoutEffect(() => {
    if (!open) {
      setDialogPos(null)
      return
    }
    positionDialogNearAnchor()
    window.addEventListener('resize', positionDialogNearAnchor)
    window.addEventListener('scroll', positionDialogNearAnchor, true)
    return () => {
      window.removeEventListener('resize', positionDialogNearAnchor)
      window.removeEventListener('scroll', positionDialogNearAnchor, true)
    }
  }, [filesExpanded, open, positionDialogNearAnchor])

  const clampDialogPos = useCallback((x: number, y: number): { x: number; y: number } => {
    const el = dialogRef.current
    const width = el?.offsetWidth ?? 512
    const height = el?.offsetHeight ?? 480
    return {
      x: Math.min(Math.max(12, x), Math.max(12, window.innerWidth - width - 12)),
      y: Math.min(Math.max(12, y), Math.max(12, window.innerHeight - height - 12))
    }
  }, [])

  const beginDialogDrag = (event: ReactPointerEvent<HTMLElement>): void => {
    if (event.button !== 0) return
    const target = event.target
    if (target instanceof Element && target.closest('button')) return

    event.preventDefault()
    endPointerDragRef.current?.()

    const startX = event.clientX
    const startY = event.clientY
    const origin = dialogPos ?? clampDialogPos(startX, startY)
    const prevCursor = document.body.style.cursor
    const prevUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'grabbing'
    document.body.style.userSelect = 'none'

    const onMove = (moveEvent: PointerEvent): void => {
      setDialogPos(
        clampDialogPos(origin.x + (moveEvent.clientX - startX), origin.y + (moveEvent.clientY - startY))
      )
    }

    const endDrag = (): void => {
      document.body.style.cursor = prevCursor
      document.body.style.userSelect = prevUserSelect
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      endPointerDragRef.current = null
    }

    const onUp = (): void => {
      endDrag()
    }

    endPointerDragRef.current = endDrag
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const selectedPaths = useMemo(
    () => resolveGitCommitPaths(gitCommitSelectedPaths, allPaths, gitCommitSelectionKey, root),
    [gitCommitSelectedPaths, allPaths, gitCommitSelectionKey, root]
  )

  const selectedSet = useMemo(() => new Set(selectedPaths), [selectedPaths])

  const pathsForBackend = (): string[] | undefined =>
    selectedPaths.length > 0 ? selectedPaths : undefined

  const generateMessage = async (): Promise<void> => {
    if (!root) {
      setError(t('operationDockCommitNoChanges'))
      return
    }
    if (selectedPaths.length === 0) {
      setError(t('operationDockCommitSelectFiles'))
      return
    }
    if (typeof window.dsGui?.suggestGitCommitMessage !== 'function') {
      setError(t('operationDockCommitUnavailable'))
      return
    }

    setGenerating(true)
    setError(null)
    try {
      const result = await window.dsGui.suggestGitCommitMessage(root, selectedPaths)
      if (!result.ok) {
        setError(result.message)
        return
      }
      setMessage(result.message)
    } catch (suggestError) {
      setError(suggestError instanceof Error ? suggestError.message : String(suggestError))
    } finally {
      setGenerating(false)
    }
  }

  const submit = async (): Promise<void> => {
    const trimmed = message.trim()
    if (!trimmed) {
      setError(t('operationDockCommitEmptyMessage'))
      return
    }
    if (!root || selectedPaths.length === 0) {
      setError(t('operationDockCommitSelectFiles'))
      return
    }
    if (typeof window.dsGui?.commitGitChanges !== 'function') {
      setError(t('operationDockCommitUnavailable'))
      return
    }

    setSubmitting(true)
    setError(null)
    try {
      const result = await window.dsGui.commitGitChanges(root, trimmed, pathsForBackend())
      if (!result.ok) {
        setError(result.message)
        return
      }
      setOpen(false)
      setMessage('')
      onCommitted?.()
    } catch (commitError) {
      setError(commitError instanceof Error ? commitError.message : String(commitError))
    } finally {
      setSubmitting(false)
    }
  }

  const close = useCallback((): void => {
    setOpen(false)
    setError(null)
  }, [])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        close()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [close, open])

  const dialog =
    open && typeof document !== 'undefined' ? (
      <div className="ds-modal-backdrop-clear ds-no-drag fixed inset-0 z-[80] pointer-events-none">
        <div
          ref={dialogRef}
          className="ds-modal-surface pointer-events-auto fixed flex w-[min(100vw-24px,32rem)] max-h-[min(88vh,680px)] flex-col overflow-hidden rounded-[22px]"
          style={
            dialogPos
              ? { left: dialogPos.x, top: dialogPos.y }
              : {
                  left: '50%',
                  top: '50%',
                  transform: 'translate(-50%, -50%)'
                }
          }
        >
          <header
            className="flex shrink-0 cursor-grab items-start justify-between gap-4 border-b border-ds-border px-5 py-4 active:cursor-grabbing"
            onPointerDown={beginDialogDrag}
          >
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <GitCommitHorizontal className="h-5 w-5 text-accent" strokeWidth={1.7} />
                <h2 className="truncate text-[18px] font-semibold text-ds-ink">
                  {t('operationDockCommitTitle')}
                </h2>
              </div>
              <p className="mt-1 text-[13px] leading-5 text-ds-muted">
                {currentBranch
                  ? t('operationDockCommitBranch', { branch: currentBranch })
                  : t('gitNoBranch')}
              </p>
              <p className="mt-0.5 text-[12px] text-ds-faint">{t('operationDockCommitFlowHint')}</p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                onClick={handleManualRefresh}
                disabled={manualRefreshing}
                className="rounded-full p-2 text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-45"
                aria-label={t('gitLogRefresh')}
                title={t('gitLogRefresh')}
              >
                <RefreshCw
                  className={`h-4 w-4 ${manualRefreshing ? 'animate-spin' : ''}`}
                  strokeWidth={1.8}
                />
              </button>
              <button
                type="button"
                onClick={close}
                className="rounded-full p-2 text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
                aria-label={t('close')}
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto">
            <section className="border-b border-ds-border-muted">
              <button
                type="button"
                className="flex w-full items-center gap-2 px-5 py-3 text-left transition hover:bg-ds-hover/40"
                onClick={() => setFilesExpanded((value) => !value)}
              >
                {filesExpanded ? (
                  <ChevronDown className="h-4 w-4 shrink-0 text-ds-faint" strokeWidth={1.85} />
                ) : (
                  <ChevronRight className="h-4 w-4 shrink-0 text-ds-faint" strokeWidth={1.85} />
                )}
                <span className="min-w-0 flex-1 text-[13px] font-medium text-ds-ink">
                  {t('operationDockCommitFilesTitle')}
                </span>
                <span className="shrink-0 text-[12px] tabular-nums text-ds-faint">
                  {t('gitCommitSelectionSummary', {
                    selected: selectedPaths.length,
                    total: Math.max(allPaths.length, gitDirtyCount)
                  })}
                </span>
              </button>

              {filesExpanded ? (
                <div className="px-5 pb-3">
                  <div className="mb-2 flex items-center justify-end gap-2 text-[12px]">
                    <button
                      type="button"
                      className="text-ds-muted transition hover:text-ds-ink"
                      onClick={() => setGitCommitSelectedPaths([...allPaths])}
                      disabled={allPaths.length === 0}
                    >
                      {t('gitCommitSelectAll')}
                    </button>
                    <span aria-hidden className="text-ds-border-strong">
                      ·
                    </span>
                    <button
                      type="button"
                      className="text-ds-muted transition hover:text-ds-ink"
                      onClick={() => setGitCommitSelectedPaths([])}
                      disabled={allPaths.length === 0}
                    >
                      {t('gitCommitSelectNone')}
                    </button>
                  </div>

                  {gitFilesLoading && allPaths.length === 0 ? (
                    <div className="flex items-center gap-2 py-6 text-[13px] text-ds-faint">
                      <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
                      {t('gitBranchLoading')}
                    </div>
                  ) : allPaths.length === 0 ? (
                    <p className="py-4 text-[13px] leading-5 text-ds-faint">
                      {gitDirtyCount > 0
                        ? t('operationDockCommitFilesLoadingFallback', { count: gitDirtyCount })
                        : t('operationDockCommitNoChanges')}
                    </p>
                  ) : (
                    <ul className="max-h-[min(36vh,260px)] overflow-y-auto rounded-xl border border-ds-border-muted/80 divide-y divide-ds-border-muted/60">
                      {gitFiles.map((file) => {
                        const checked = selectedSet.has(file.path)
                        const stats = countDiffStats(file.patch)
                        const displayPath = formatFilePathForDisplay(file.path, root)
                        return (
                          <li key={file.path}>
                            <label className="flex cursor-pointer items-start gap-2.5 px-3 py-2.5 transition hover:bg-ds-hover/50">
                              <input
                                type="checkbox"
                                checked={checked}
                                className="mt-1 shrink-0"
                                onChange={() => toggleGitCommitPath(file.path, allPaths)}
                              />
                              <span className="min-w-0 flex-1">
                                <span className="block truncate text-[13px] text-ds-ink">
                                  {displayPath ?? file.path}
                                </span>
                                <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
                                  <span className="rounded-full bg-ds-hover px-1.5 py-0.5 text-[10px] font-medium text-ds-muted">
                                    {gitStatusLabel(file.status, t)}
                                  </span>
                                  <span className="rounded-full bg-ds-hover px-1.5 py-0.5 text-[10px] font-medium text-ds-muted">
                                    {gitStageLabel(file.stage, t)}
                                  </span>
                                  {stats ? <ChangeDiffStatsLabel stats={stats} size="sm" /> : null}
                                </span>
                              </span>
                            </label>
                          </li>
                        )
                      })}
                    </ul>
                  )}
                </div>
              ) : null}
            </section>

            <section className="space-y-3 px-5 py-4">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-medium text-ds-ink">
                  {t('operationDockCommitMessage')}
                </span>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 rounded-lg border border-ds-border px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:cursor-not-allowed disabled:opacity-45"
                  onClick={() => void generateMessage()}
                  disabled={submitting || generating || selectedPaths.length === 0}
                >
                  {generating ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
                      {t('operationDockCommitGenerating')}
                    </>
                  ) : (
                    t('operationDockCommitGenerate')
                  )}
                </button>
              </div>
              <textarea
                value={message}
                onChange={(event) => {
                  setMessage(event.target.value)
                  if (error) setError(null)
                }}
                rows={5}
                placeholder={t('operationDockCommitMessagePlaceholder')}
                className="w-full resize-none rounded-xl border border-ds-border bg-ds-card px-3 py-2.5 text-[13px] leading-5 text-ds-ink outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/20"
                onKeyDown={(event) => {
                  if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                    event.preventDefault()
                    void submit()
                  }
                }}
              />

              {error ? (
                <div className="flex gap-2 rounded-lg border border-amber-300/70 bg-amber-50 px-3 py-2 text-[12px] leading-5 text-amber-900 dark:border-amber-700/50 dark:bg-amber-950/35 dark:text-amber-100">
                  <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" strokeWidth={2} />
                  <span className="min-w-0 break-words">{error}</span>
                </div>
              ) : null}
            </section>
          </div>

          <footer className="flex shrink-0 items-center justify-end gap-2 border-t border-ds-border px-5 py-4">
            <button
              type="button"
              className="rounded-lg px-3 py-1.5 text-[13px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
              onClick={close}
              disabled={submitting}
            >
              {t('operationDockCommitCancel')}
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-[13px] font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => void submit()}
              disabled={submitting || selectedPaths.length === 0}
            >
              {submitting ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
                  {t('operationDockCommitSubmitting')}
                </>
              ) : (
                t('operationDockCommitSubmit')
              )}
            </button>
          </footer>
        </div>
      </div>
    ) : null

  const menu =
    menuOpen && typeof document !== 'undefined' ? (
      <div className="ds-card-strong ds-no-drag absolute right-0 top-full z-20 mt-1 w-44 overflow-hidden rounded-xl border border-ds-border py-1 shadow-lg">
        <button
          type="button"
          className="block w-full px-3 py-2 text-left text-[13px] text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-45"
          disabled={!onOpenChanges}
          onClick={() => {
            setMenuOpen(false)
            onOpenChanges?.()
          }}
        >
          {t('operationDockCommitViewChanges')}
        </button>
      </div>
    ) : null

  return (
    <div ref={anchorRef} className="ds-no-drag relative">
      <div
        className={`${rowClassName} ${
          enabled
            ? 'text-ds-muted hover:bg-ds-hover/60 hover:text-ds-ink'
            : 'cursor-default text-ds-faint opacity-55'
        }`}
      >
        <button
          type="button"
          disabled={!enabled}
          className={`flex min-w-0 flex-1 items-center gap-2 text-left ${
            enabled ? 'cursor-pointer' : 'cursor-default'
          }`}
          onClick={() => {
            if (!enabled) return
            setMenuOpen(false)
            setOpen(true)
          }}
        >
          <GitCommitHorizontal className="h-4 w-4 shrink-0" strokeWidth={1.85} />
          <span className="min-w-0 flex-1 truncate">{t('operationDockCommit')}</span>
        </button>
        <button
          type="button"
          className="relative shrink-0 rounded-md p-0.5 text-ds-faint transition hover:bg-ds-hover/70 hover:text-ds-ink"
          aria-label={t('operationDockGitMore')}
          onClick={(event) => {
            event.stopPropagation()
            setOpen(false)
            setMenuOpen((value) => !value)
          }}
        >
          <MoreHorizontal className="h-4 w-4" strokeWidth={1.9} />
          {menu}
        </button>
      </div>

      {typeof document !== 'undefined' ? createPortal(dialog, document.body) : null}
    </div>
  )
}
