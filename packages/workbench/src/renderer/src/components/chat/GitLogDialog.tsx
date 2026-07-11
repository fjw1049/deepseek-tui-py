import { useCallback, useEffect, useMemo, useState, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import { AlertCircle, GitCommitHorizontal, Loader2, RefreshCw, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { GitLogCommit, GitLogResult } from '@shared/git-log'
import { computeGitGraphLayout, GIT_GRAPH_ROW_HEIGHT } from '../../lib/git-graph-layout'
import { GitGraphSvg } from './GitGraphSvg'

type Props = {
  workspaceRoot: string
  currentBranch: string | null
  open: boolean
  onClose: () => void
}

function formatCommitDate(iso: string): string {
  const date = new Date(iso)
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  return `${month}/${day} ${hours}:${minutes}`
}

function commitTags(
  commit: GitLogCommit,
  log: Extract<GitLogResult, { ok: true }>
): Array<{ key: string; label: string; tone: 'head' | 'branch' | 'remote' }> {
  const tags: Array<{ key: string; label: string; tone: 'head' | 'branch' | 'remote' }> = []
  if (commit.hash === log.headHash) {
    tags.push({ key: 'head', label: 'HEAD', tone: 'head' })
    if (log.branch) {
      tags.push({ key: `branch-${log.branch}`, label: log.branch, tone: 'branch' })
    }
  }
  if (log.upstream && commit.hash === log.upstream.hash) {
    tags.push({ key: `upstream-${log.upstream.ref}`, label: log.upstream.ref, tone: 'remote' })
  }
  return tags
}

function tagClassName(tone: 'head' | 'branch' | 'remote'): string {
  if (tone === 'head') {
    return 'border-emerald-300/70 bg-emerald-50 text-emerald-900 dark:border-emerald-700/50 dark:bg-emerald-950/40 dark:text-emerald-100'
  }
  if (tone === 'remote') {
    return 'border-amber-300/70 bg-amber-50 text-amber-900 dark:border-amber-700/50 dark:bg-amber-950/40 dark:text-amber-100'
  }
  return 'border-sky-300/70 bg-sky-50 text-sky-900 dark:border-sky-700/50 dark:bg-sky-950/40 dark:text-sky-100'
}

export function GitLogDialog({
  workspaceRoot,
  currentBranch,
  open,
  onClose
}: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const root = workspaceRoot.trim()
  const [result, setResult] = useState<GitLogResult | null>(null)
  const [loading, setLoading] = useState(false)

  const reload = useCallback(async (): Promise<void> => {
    if (!root) {
      setResult(null)
      setLoading(false)
      return
    }
    if (typeof window.dsGui?.getGitLog !== 'function') {
      setResult({
        ok: false,
        reason: 'error',
        message: t('gitLogUnavailable')
      })
      setLoading(false)
      return
    }
    const requestRoot = root
    setLoading(true)
    try {
      const next = await window.dsGui.getGitLog(requestRoot)
      setResult(next)
    } catch (error) {
      setResult({
        ok: false,
        reason: 'error',
        message: error instanceof Error ? error.message : String(error)
      })
    } finally {
      setLoading(false)
    }
  }, [root, t])

  useEffect(() => {
    if (!open) {
      setResult(null)
      return
    }
    void reload()
  }, [open, reload])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose, open])

  const log = result?.ok ? result : null
  const errorMessage = result && !result.ok ? result.message : null
  const titleBranch = log?.branch ?? currentBranch ?? t('gitDetached')

  const summary = useMemo(() => {
    if (!log?.upstream) return null
    const { ahead, behind } = log.upstream
    if (ahead === 0 && behind === 0) return t('gitLogInSync')
    const parts: string[] = []
    if (ahead > 0) parts.push(t('gitLogAhead', { count: ahead }))
    if (behind > 0) parts.push(t('gitLogBehind', { count: behind }))
    return parts.join(' · ')
  }, [log, t])

  const graphLayout = useMemo(
    () => (log ? computeGitGraphLayout(log.commits) : null),
    [log]
  )

  const graphWidth = graphLayout?.graphWidth ?? 28

  if (!open || typeof document === 'undefined') return null

  return createPortal(
    <div
      className="ds-modal-backdrop ds-no-drag fixed inset-0 z-[80] flex items-center justify-center p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="ds-modal-surface flex h-[min(88vh,760px)] w-full max-w-5xl flex-col overflow-hidden rounded-[14px]">
        <header className="flex shrink-0 items-start justify-between gap-4 border-b border-ds-border px-5 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <GitCommitHorizontal className="h-5 w-5 text-accent" strokeWidth={1.7} />
              <h2 className="truncate text-[18px] font-semibold text-ds-ink">{t('gitLogTitle')}</h2>
            </div>
            <p className="mt-1 text-[13px] leading-5 text-ds-muted">
              <span className="font-medium text-ds-ink">{titleBranch}</span>
              {summary ? <span className="text-ds-faint"> · {summary}</span> : null}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={() => void reload()}
              disabled={loading}
              className="rounded-full p-2 text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-45"
              aria-label={t('gitLogRefresh')}
              title={t('gitLogRefresh')}
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} strokeWidth={1.8} />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-full p-2 text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
              aria-label={t('close')}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex min-h-[320px] items-center justify-center text-ds-muted">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              {t('gitLogLoading')}
            </div>
          ) : errorMessage ? (
            <div className="flex min-h-[320px] gap-2 px-5 py-4 text-[13px] leading-5 text-amber-900 dark:text-amber-100">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" strokeWidth={2} />
              <span className="min-w-0 break-words">{errorMessage}</span>
            </div>
          ) : log && log.commits.length === 0 ? (
            <div className="flex min-h-[320px] items-center justify-center px-5 text-[13px] text-ds-faint">
              {t('gitLogEmpty')}
            </div>
          ) : log && graphLayout ? (
            <div className="relative py-1">
              <div className="pointer-events-none absolute left-4 top-1" aria-hidden>
                <GitGraphSvg layout={graphLayout} headHash={log.headHash} />
              </div>
              <ul>
                {log.commits.map((commit, index) => {
                  const tags = commitTags(commit, log)
                  const isHead = commit.hash === log.headHash
                  const isMainline = graphLayout.rows[index]?.isMainline ?? true
                  return (
                    <li
                      key={commit.hash}
                      className={`grid h-9 items-center gap-x-3 border-b border-ds-border-muted/55 px-4 ${
                        isHead ? 'bg-accent/[0.05]' : index % 2 === 1 ? 'bg-ds-subtle/30' : ''
                      }`}
                      style={{
                        gridTemplateColumns: `${graphWidth}px minmax(0,1fr) 88px 80px 64px`,
                        minHeight: GIT_GRAPH_ROW_HEIGHT
                      }}
                    >
                      <div aria-hidden />

                      <div className="flex min-w-0 items-center">
                        <div className="flex min-w-0 items-center gap-2">
                          {tags.length > 0 ? (
                            <div className="flex shrink-0 flex-wrap gap-1">
                              {tags.map((tag) => (
                                <span
                                  key={tag.key}
                                  className={`inline-flex rounded-md border px-1.5 py-0.5 text-[10px] font-semibold leading-none ${tagClassName(tag.tone)}`}
                                >
                                  {tag.label}
                                </span>
                              ))}
                            </div>
                          ) : null}
                          <p
                            className={`min-w-0 truncate text-[13px] leading-5 ${
                              isMainline ? 'text-ds-ink' : 'text-ds-faint'
                            }`}
                            title={commit.subject}
                          >
                            {commit.subject}
                          </p>
                        </div>
                      </div>

                      <span className="truncate text-[12px] tabular-nums text-ds-faint">
                        {formatCommitDate(commit.authoredAt)}
                      </span>
                      <span
                        className={`truncate text-[12px] ${isMainline ? 'text-ds-muted' : 'text-ds-faint'}`}
                        title={commit.author}
                      >
                        {commit.author}
                      </span>
                      <span className="truncate font-mono text-[11px] tabular-nums text-ds-faint">
                        {commit.shortHash}
                      </span>
                    </li>
                  )
                })}
              </ul>
            </div>
          ) : (
            <div className="flex min-h-[320px] items-center justify-center px-5 text-[13px] text-ds-faint">
              {t('gitLogEmpty')}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  )
}
