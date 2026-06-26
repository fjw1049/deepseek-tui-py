import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactElement
} from 'react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import { FileEdit, PanelRightClose } from 'lucide-react'
import type { GitWorkingChangeFile } from '@shared/git-working-changes'
import type { ChatBlock } from '../agent/types'
import { ChangeDiffStatsLabel } from './ChangeDiffStatsLabel'
import { useGitWorkingChanges } from '../hooks/use-git-working-changes'
import {
  countDiffStats,
  extractDiffFilePath,
  formatFilePathForDisplay,
  looksLikeUnifiedDiff,
  sumDiffStats
} from '../lib/diff-stats'
import { resolveActiveThreadWorkspace } from '../lib/workspace-path'
import { useChatStore } from '../store/chat-store'
import { DiffView } from './DiffView'

const LIST_HEIGHT_KEY = 'deepseekgui.layout.changeInspectorListHeight'
const DEFAULT_LIST_HEIGHT = 240
const MIN_LIST_HEIGHT = 108
const MIN_DIFF_HEIGHT = 128
const SPLIT_HANDLE_HEIGHT = 8

type InspectorChangeItem = {
  id: string
  filePath?: string
  detail: string
  status: 'running' | 'success' | 'error'
}

function readStoredListHeight(): number {
  try {
    const raw = window.localStorage.getItem(LIST_HEIGHT_KEY)
    const parsed = raw ? Number.parseInt(raw, 10) : Number.NaN
    if (Number.isFinite(parsed) && parsed >= MIN_LIST_HEIGHT) return parsed
  } catch {
    /* ignore */
  }
  return DEFAULT_LIST_HEIGHT
}

function persistListHeight(height: number): void {
  try {
    window.localStorage.setItem(LIST_HEIGHT_KEY, String(Math.round(height)))
  } catch {
    /* ignore */
  }
}

function normalizeChangePath(path: string | undefined): string {
  return (path ?? '').replace(/\\/g, '/').trim().toLowerCase()
}

function sessionChangeItems(blocks: ChatBlock[]): InspectorChangeItem[] {
  return blocks.flatMap((block): InspectorChangeItem[] => {
    if (!(block.kind === 'tool' && block.toolKind === 'file_change')) {
      return []
    }

    const detailText = block.detail?.trim() ?? ''
    if (!looksLikeUnifiedDiff(detailText)) return []

    return [
      {
        id: block.id,
        filePath: extractDiffFilePath(detailText, block.filePath),
        detail: detailText,
        status: block.status
      }
    ]
  })
}

function gitChangeItems(files: GitWorkingChangeFile[]): InspectorChangeItem[] {
  return files.map((file) => ({
    id: `git:${file.path}`,
    filePath: file.path,
    detail: file.patch,
    status: 'success' as const
  }))
}

function mergeChangeItems(
  sessionItems: InspectorChangeItem[],
  gitItems: InspectorChangeItem[]
): InspectorChangeItem[] {
  const seen = new Set<string>()
  const merged: InspectorChangeItem[] = []

  for (const item of [...sessionItems, ...gitItems]) {
    const key = normalizeChangePath(item.filePath) || item.id
    if (seen.has(key)) continue
    seen.add(key)
    merged.push(item)
  }

  return merged
}

/**
 * Right-side change inspector — session file_change items plus Git working-tree changes.
 * Selecting a row reveals the unified patch in the bottom panel.
 */
export function ChangeInspector({
  blocks,
  className,
  onCollapse
}: {
  blocks: ChatBlock[]
  className?: string
  onCollapse: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const selectedId = useChatStore((s) => s.inspectorSelectedId)
  const selectInspectorItem = useChatStore((s) => s.selectInspectorItem)
  const { workspaceRoot, activeThreadId, threads } = useChatStore(
    useShallow((s) => ({
      workspaceRoot: s.workspaceRoot,
      activeThreadId: s.activeThreadId,
      threads: s.threads
    }))
  )
  const root = resolveActiveThreadWorkspace(activeThreadId, threads, workspaceRoot)
  const { result: gitChanges, loading: gitLoading } = useGitWorkingChanges(root)
  const splitContainerRef = useRef<HTMLDivElement>(null)
  const [listHeight, setListHeight] = useState(readStoredListHeight)

  const fileChanges = useMemo(() => {
    const sessionItems = sessionChangeItems(blocks)
    const gitItems = gitChanges?.ok ? gitChangeItems(gitChanges.files) : []
    return mergeChangeItems(sessionItems, gitItems)
  }, [blocks, gitChanges])

  const changeStats = useMemo(
    () => sumDiffStats(fileChanges.map((item) => item.detail)),
    [fileChanges]
  )

  useEffect(() => {
    if (fileChanges.length === 0) {
      if (selectedId !== null) selectInspectorItem(null)
      return
    }
    if (selectedId && fileChanges.some((item) => item.id === selectedId)) return
    selectInspectorItem(fileChanges[fileChanges.length - 1]?.id ?? null)
  }, [fileChanges, selectedId, selectInspectorItem])

  const clampListHeight = useCallback((next: number): number => {
    const containerHeight = splitContainerRef.current?.clientHeight ?? 0
    const maxListHeight = Math.max(
      MIN_LIST_HEIGHT,
      containerHeight - MIN_DIFF_HEIGHT - SPLIT_HANDLE_HEIGHT
    )
    return Math.min(Math.max(next, MIN_LIST_HEIGHT), maxListHeight)
  }, [])

  useEffect(() => {
    setListHeight((current) => clampListHeight(current))
  }, [clampListHeight, fileChanges.length])

  const beginSplitResize = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0) return
    event.preventDefault()

    const startY = event.clientY
    const startHeight = listHeight
    const prevCursor = document.body.style.cursor
    const prevUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'row-resize'
    document.body.style.userSelect = 'none'

    const onMove = (moveEvent: PointerEvent): void => {
      const next = clampListHeight(startHeight + (moveEvent.clientY - startY))
      setListHeight(next)
    }

    const onUp = (): void => {
      document.body.style.cursor = prevCursor
      document.body.style.userSelect = prevUserSelect
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      setListHeight((current) => {
        persistListHeight(current)
        return current
      })
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const active =
    fileChanges.find((item) => item.id === selectedId) ?? fileChanges[fileChanges.length - 1]

  return (
    <aside
      className={`ds-change-inspector ds-tool-panel ds-no-drag flex flex-col ${className ?? ''}`}
    >
      <div className="flex min-h-[58px] shrink-0 items-center gap-3 border-b border-ds-border-muted px-3 py-3">
        <button
          type="button"
          onClick={onCollapse}
          className="ds-sidebar-toggle-button shrink-0"
          aria-label={t('rightPanelCollapse')}
          title={t('rightPanelCollapse')}
        >
          <PanelRightClose className="h-4 w-4" strokeWidth={1.85} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <div className="text-[13px] font-semibold tracking-wide text-ds-muted">
              {t('inspectorTitle')}
            </div>
            {changeStats ? <ChangeDiffStatsLabel stats={changeStats} size="md" /> : null}
          </div>
          <div className="mt-1 truncate text-[12px] text-ds-faint">
            {gitLoading && fileChanges.length === 0
              ? t('gitBranchLoading')
              : fileChanges.length > 0
                ? t('inspectorSummaryFiles', { count: fileChanges.length })
                : t('inspectorEmpty')}
          </div>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col">
        {gitLoading && fileChanges.length === 0 ? (
          <div className="flex flex-1 items-center justify-center px-6 py-10 text-center text-[13px] text-ds-faint">
            {t('gitBranchLoading')}
          </div>
        ) : fileChanges.length === 0 ? (
          <div className="flex flex-1 items-center justify-center px-6 py-10 text-center">
            <div>
              <FileEdit className="mx-auto h-7 w-7 text-ds-faint" strokeWidth={1.25} />
              <div className="mt-3 text-[13px] font-medium text-ds-muted">
                {t('inspectorEmptyTitle')}
              </div>
              <div className="mt-1 text-[12px] leading-6 text-ds-faint">{t('inspectorEmpty')}</div>
            </div>
          </div>
        ) : (
          <div ref={splitContainerRef} className="flex min-h-0 flex-1 flex-col">
            <div
              className="min-h-0 shrink-0 overflow-y-auto py-2"
              style={{ height: listHeight }}
            >
              <ul className="divide-y divide-ds-border-muted/60">
                {fileChanges.map((item) => {
                  const stats = countDiffStats(item.detail)
                  const displayPath = formatFilePathForDisplay(item.filePath, root || workspaceRoot)
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => selectInspectorItem(item.id)}
                        className={`flex w-full items-start gap-2.5 px-4 py-2.5 text-left transition ${
                          active?.id === item.id
                            ? 'bg-ds-hover text-ds-ink'
                            : 'text-ds-ink hover:bg-ds-hover/70'
                        }`}
                      >
                        <FileEdit
                          className={`mt-0.5 h-4 w-4 shrink-0 ${
                            item.status === 'error' ? 'text-red-700' : 'text-ds-muted'
                          }`}
                          strokeWidth={1.75}
                        />
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-[13px] text-ds-ink">
                            {displayPath ?? t('toolActionFile')}
                          </div>
                          {stats ? (
                            <div className="mt-0.5">
                              <ChangeDiffStatsLabel stats={stats} size="sm" />
                            </div>
                          ) : null}
                        </div>
                        {item.status === 'running' ? (
                          <span className="rounded-full bg-amber-200/40 px-2 py-0.5 text-[11px] font-medium text-amber-900 dark:bg-amber-700/30 dark:text-amber-100">
                            {t('inspectorStatusRunning')}
                          </span>
                        ) : null}
                      </button>
                    </li>
                  )
                })}
              </ul>
            </div>

            <div
              role="separator"
              aria-orientation="horizontal"
              aria-label={t('inspectorResizeSplit')}
              className="ds-change-inspector__split-handle ds-no-drag group relative z-10 shrink-0 cursor-row-resize"
              style={{ height: SPLIT_HANDLE_HEIGHT }}
              onPointerDown={beginSplitResize}
            >
              <div className="absolute inset-x-3 top-1/2 h-px -translate-y-1/2 bg-ds-border-muted/80 transition group-hover:bg-ds-border-strong" />
            </div>

            <div className="ds-panel-strip flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
              {active?.detail ? (
                <DiffView
                  patch={active.detail}
                  filePath={active.filePath}
                  maxHeight={9999}
                  className="ds-change-inspector__code h-full min-w-0 rounded-none border-0"
                />
              ) : (
                <div className="ds-surface-soft flex h-full items-center justify-center border border-dashed border-ds-border-muted px-4 py-6 text-center text-[12px] leading-6 text-ds-muted">
                  {t('inspectorSelectHint')}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </aside>
  )
}
