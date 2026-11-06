import type { MouseEvent as ReactMouseEvent, ReactElement } from 'react'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ChevronsDownUp, ChevronsUpDown, ChevronRight, RefreshCw, Folder, FolderOpen, Eye } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { WorkspaceTreeEntry } from '@shared/workspace-file'
import { FileKindIcon } from '../chat/FileKindIcon'
import { Tooltip } from '../common/Tooltip'
import { formatFilePathForDisplay } from '../../lib/diff-stats'
import { directoryHasChanges, pathHasChanges } from '../../lib/workspace-change-patches'
import { setWorkspacePathDragData } from '../../lib/composer-insert'
import { useWorkspaceDirtyGitRefresh } from '../../hooks/use-workspace-dirty-git-refresh'
import {
  readExpandedDirs,
  writeExpandedDirs
} from '../../lib/workspace-file-tree-expand-cache'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import i18n from '../../i18n'
import { isAuxiliaryWorkspaceEntry } from '../../lib/workspace-tree-filter'
import { useWorkspaceViewPreferences } from '../../store/workspace-view-preferences'

type TreeNodeState = {
  entries: WorkspaceTreeEntry[]
  loaded: boolean
  error: string | null
}

type Props = {
  workspaceRoot: string
  activePaths?: string[]
  dirtyPaths?: Set<string>
  patchMap?: Map<string, string>
  workspaceDirtyTick?: number
  onOpenFile: (path: string) => void
  onFileContextMenu?: (event: ReactMouseEvent, path: string) => void
}

/** Tree keys: posix + lower-case so clicks and cache always agree. */
function treeKey(path: string): string {
  return path.replace(/\\/g, '/').replace(/^\/+/, '').trim().toLowerCase()
}

async function fetchDirectory(
  workspaceRoot: string,
  directoryPath: string
): Promise<{ ok: true; entries: WorkspaceTreeEntry[] } | { ok: false; message: string }> {
  if (typeof window.dsGui?.listWorkspaceDirectory !== 'function') {
    return { ok: false, message: 'workspaceTreeUnavailable' }
  }

  try {
    const result = await window.dsGui.listWorkspaceDirectory(workspaceRoot, directoryPath, true)
    if (result.ok) {
      return { ok: true, entries: result.entries }
    }
    return { ok: false, message: result.message }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    if (message.includes('No handler registered for')) {
      return { ok: false, message: 'workspaceTreeRestartRequired' }
    }
    return { ok: false, message }
  }
}

function translateTreeError(message: string): string {
  if (message === 'workspaceTreeUnavailable') {
    return i18n.t('common:workspaceTreeUnavailable')
  }
  if (message === 'workspaceTreeRestartRequired') {
    return i18n.t('common:workspaceTreeRestartRequired')
  }
  return message
}

function indentPx(depth: number): number {
  return depth * 16 + 8
}

/**
 * VS Code-style explorer: click a folder row to expand/collapse.
 * Expand state is user-driven only — git/patch refresh must not reopen folders.
 */
export function WorkspaceFileTree({
  workspaceRoot,
  activePaths,
  dirtyPaths,
  patchMap,
  workspaceDirtyTick = 0,
  onOpenFile,
  onFileContextMenu
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const showAllFiles = useWorkspaceViewPreferences((s) => s.showAllFiles)
  const setShowAllFiles = useWorkspaceViewPreferences((s) => s.setShowAllFiles)
  const trimmedRoot = workspaceRoot.trim()
  const workspaceLabel = workspaceLabelFromPath(trimmedRoot) || trimmedRoot
  const activeKeys = new Set((activePaths ?? []).map(treeKey).filter(Boolean))
  const trimmedRootRef = useRef(trimmedRoot)
  trimmedRootRef.current = trimmedRoot
  const nodesRef = useRef<Record<string, TreeNodeState>>({})
  const [nodes, setNodes] = useState<Record<string, TreeNodeState>>({})
  const [expanded, setExpanded] = useState(() => readExpandedDirs(trimmedRoot))
  const expandedRef = useRef(expanded)
  const operation = useRef(0)
  const [expanding, setExpanding] = useState(false)
  const expandIntent = useRef(false)
  const [refreshing, setRefreshing] = useState(false)
  const refreshPending = useRef(false)
  const refreshRunning = useRef(false)
  const filterRef = useRef(showAllFiles)
  filterRef.current = showAllFiles
  const persistTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const persistPending = useRef<(() => void) | null>(null)

  const updateExpanded = useCallback((next: Set<string>): void => {
    expandedRef.current = next
    setExpanded(next)
    const root = trimmedRootRef.current
    persistPending.current = () => writeExpandedDirs(root, next)
    if (persistTimer.current) clearTimeout(persistTimer.current)
    persistTimer.current = setTimeout(() => {
      persistPending.current?.()
      persistPending.current = null
      persistTimer.current = null
    }, 250)
  }, [])

  // Share the limit across cancelled scans: already-issued IPC cannot be aborted.
  const requests = useRef({ active: 0, waiting: [] as Array<() => void> })
  const readDirectory = useCallback(async (root: string, path: string, version: number) => {
    const queue = requests.current
    await new Promise<void>((resolve) => {
      const start = (): void => { queue.active += 1; resolve() }
      if (queue.active < 4) start()
      else queue.waiting.push(start)
    })
    try {
      if (operation.current !== version) return null
      return await fetchDirectory(root, path)
    } finally {
      queue.active -= 1
      queue.waiting.shift()?.()
    }
  }, [])

  const scan = useCallback(async (openAll = false): Promise<void> => {
    const root = trimmedRootRef.current
    const version = ++operation.current
    expandIntent.current = openAll
    setExpanding(openAll)
    if (!root) return
    const cache = { ...nodesRef.current }
    nodesRef.current = cache
    const expandedKeys = new Set(expandedRef.current)
    let nodesChanged = true
    let expansionChanged = false
    const publish = (): void => {
      if (nodesChanged) setNodes({ ...cache })
      if (expansionChanged) updateExpanded(new Set(expandedKeys))
      nodesChanged = false
      expansionChanged = false
    }
    const queue = ['']
    let cursor = 0
    let lastYield = performance.now()
    while (cursor < queue.length && operation.current === version) {
      const paths = queue.slice(cursor, cursor + 4)
      cursor += paths.length
      const results = await Promise.all(paths.map(async (path) => {
        const cached = cache[treeKey(path)]
        if (cached?.loaded) return { path, node: cached, changed: false }
        const result = await readDirectory(root, path, version)
        if (!result) return null
        return { path, changed: true, node: {
          entries: result.ok ? result.entries : [], loaded: true,
          error: result.ok ? null : translateTreeError(result.message)
        } }
      }))
      if (operation.current !== version) return
      for (const result of results) {
        if (!result) continue
        const { path, node, changed } = result
        if (changed) {
          cache[treeKey(path)] = node
          nodesChanged = true
        }
        for (const entry of node.entries) {
          if (entry.kind !== 'directory' || (!filterRef.current && isAuxiliaryWorkspaceEntry(entry))) continue
          const key = treeKey(entry.path)
          if (openAll && !expandedKeys.has(key)) {
            expandedKeys.add(key)
            expansionChanged = true
          }
          if (expandedKeys.has(key)) queue.push(entry.path)
        }
      }
      if (performance.now() - lastYield >= 16) {
        publish()
        await new Promise((resolve) => setTimeout(resolve, 0))
        lastYield = performance.now()
      }
    }
    if (operation.current === version) {
      publish()
      expandIntent.current = false
      setExpanding(false)
    }
  }, [readDirectory, updateExpanded])

  const refreshLoadedDirectories = useCallback(async (): Promise<void> => {
    refreshPending.current = true
    if (refreshRunning.current) return
    refreshRunning.current = true
    setRefreshing(true)
    try {
      while (refreshPending.current) {
        refreshPending.current = false
        // Hidden directories become stale; scan only follows expanded ancestors.
        nodesRef.current = Object.fromEntries(Object.entries(nodesRef.current)
          .map(([key, node]) => [key, { ...node, loaded: false }]))
        await scan(expandIntent.current)
      }
    } finally {
      refreshRunning.current = false
      setRefreshing(false)
    }
  }, [scan])

  useWorkspaceDirtyGitRefresh(workspaceDirtyTick, refreshLoadedDirectories)

  useEffect(() => {
    nodesRef.current = {}
    setNodes({})
    expandedRef.current = new Set([...readExpandedDirs(trimmedRoot)].map(treeKey))
    setExpanded(expandedRef.current)
    void scan()
    return () => {
      operation.current += 1
      refreshPending.current = false
      if (persistTimer.current) clearTimeout(persistTimer.current)
      persistPending.current?.()
      persistPending.current = null
    }
  }, [trimmedRoot, scan])

  const previousFilter = useRef(showAllFiles)
  useEffect(() => {
    if (previousFilter.current === showAllFiles) return
    previousFilter.current = showAllFiles
    void scan()
  }, [showAllFiles, scan])

  const lastRevealedActiveRef = useRef('')
  useEffect(() => {
    const active = (activePaths ?? []).find(Boolean)
    const identity = `${trimmedRoot}:${active ?? ''}`
    if (!active || identity === lastRevealedActiveRef.current) return
    lastRevealedActiveRef.current = identity
    const parts = active.replace(/\\/g, '/').split('/').filter(Boolean)
    const next = new Set(expandedRef.current)
    for (let i = 1; i < parts.length; i += 1) next.add(treeKey(parts.slice(0, i).join('/')))
    if (next.size === expandedRef.current.size) return
    updateExpanded(next)
    void scan()
  }, [activePaths, trimmedRoot, updateExpanded, scan])

  const toggleDirectory = useCallback((path: string): void => {
    const next = new Set(expandedRef.current)
    const key = treeKey(path)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    updateExpanded(next)
    void scan()
  }, [updateExpanded, scan])

  const [flashPaths, setFlashPaths] = useState<Record<string, number>>({})
  const previousNodes = useRef<Record<string, TreeNodeState>>({})
  useEffect(() => {
    previousNodes.current = {}
    setFlashPaths({})
  }, [trimmedRoot])
  useEffect(() => {
    const fresh: Record<string, number> = {}
    for (const [key, node] of Object.entries(nodes)) {
      const previous = previousNodes.current[key]
      // Expanding an existing directory is not a new-file event.
      if (!previous || previous.entries === node.entries) continue
      const seen = new Set(previous.entries.map((entry) => treeKey(entry.path)))
      for (const entry of node.entries) {
        const path = treeKey(entry.path)
        if (entry.kind !== 'directory' && !seen.has(path)) fresh[path] = Date.now() + 2000
      }
    }
    previousNodes.current = nodes
    if (Object.keys(fresh).length) setFlashPaths((previous) => ({ ...previous, ...fresh }))
  }, [nodes])
  useEffect(() => {
    if (!Object.keys(flashPaths).length) return
    const timer = window.setTimeout(() => setFlashPaths({}), 2200)
    return () => window.clearTimeout(timer)
  }, [flashPaths])

  const collapseAll = useCallback((): void => {
    operation.current += 1
    setExpanding(false)
    updateExpanded(new Set())
    void scan()
  }, [updateExpanded, scan])

  const anyExpanded = expanding || [...expanded].some(Boolean)

  type Row = { key: string; depth: number; trunks: number[]; last?: boolean; entry?: WorkspaceTreeEntry; message?: string; error?: boolean }
  const rows = useMemo(() => {
    const result: Row[] = []
    const visit = (path: string, depth: number, trunks: number[]): void => {
      const key = treeKey(path)
      const node = nodes[key]
      if (!node) {
        result.push({ key: `${key}__loading`, depth, trunks, message: '…' })
        return
      }
      if (node.error) {
        result.push({ key: `${key}__error`, depth, trunks, message: node.error, error: true })
        return
      }
      const entries = showAllFiles ? node.entries : node.entries.filter((entry) => !isAuxiliaryWorkspaceEntry(entry))
      if (!entries.length) result.push({ key: `${key}__empty`, depth, trunks, message: t(node.entries.length ? 'workspaceTreeFilteredEmpty' : 'workspaceTreeEmpty') })
      for (const [index, entry] of entries.entries()) {
        const last = index === entries.length - 1
        result.push({ key: treeKey(entry.path), depth, trunks, last, entry })
        if (entry.kind === 'directory' && expanded.has(treeKey(entry.path))) {
          visit(entry.path, depth + 1, depth > 0 && !last ? [...trunks, depth - 1] : trunks)
        }
      }
    }
    if (trimmedRoot) visit('', 0, [])
    return result
  }, [nodes, expanded, showAllFiles, trimmedRoot, t])

  const dirtyKeys = useMemo(() => new Set([...(dirtyPaths ?? [])].map(treeKey)), [dirtyPaths])
  const scrollRef = useRef<HTMLDivElement>(null)
  const [viewport, setViewport] = useState({ top: 0, height: 560 })
  useLayoutEffect(() => {
    const element = scrollRef.current
    if (!element) return
    const measure = (): void => setViewport({ top: element.scrollTop, height: element.clientHeight || 560 })
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  useLayoutEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0
    setViewport((previous) => ({ ...previous, top: 0 }))
  }, [trimmedRoot])
  const rowHeight = 28
  const scrollTop = Math.min(viewport.top, Math.max(0, rows.length * rowHeight - viewport.height))
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - 8)
  const end = Math.min(rows.length, Math.ceil((scrollTop + viewport.height) / rowHeight) + 8)
  useLayoutEffect(() => {
    if (scrollRef.current && viewport.top !== scrollTop) {
      scrollRef.current.scrollTop = scrollTop
      setViewport((previous) => ({ ...previous, top: scrollTop }))
    }
  }, [scrollTop, viewport.top])

  const pendingFocus = useRef<string | null>(null)
  useLayoutEffect(() => {
    if (!pendingFocus.current) return
    const button = [...(scrollRef.current?.querySelectorAll<HTMLButtonElement>('[data-tree-key]') ?? [])]
      .find((element) => element.dataset.treeKey === pendingFocus.current)
    if (button) {
      button.focus({ preventScroll: true })
      pendingFocus.current = null
    }
  }, [start, end, rows, viewport])

  const renderRow = ({ key, entry, depth, trunks, last = true, message, error }: Row): ReactElement => {
    const branchX = indentPx(depth - 1) + 7
    const isExpanded = entry?.kind === 'directory' && expanded.has(key)
    const guides = (depth > 0 || isExpanded) && (
      <svg className="ds-tree-guides" width={indentPx(depth) + 9} height={rowHeight} aria-hidden>
        {trunks.map((level) => {
          const x = indentPx(level) + 7
          return <path key={level} d={`M${x} 0v${rowHeight}`} />
        })}
        {depth > 0 && <path d={`M${branchX} 0v9q0 5 5 5h5`} />}
        {isExpanded && <path d={`M${indentPx(depth) + 7} 21V${rowHeight}`} />}
        {depth > 0 && !last && <path d={`M${branchX} 9v${rowHeight - 9}`} />}
      </svg>
    )
    if (!entry) return <div key={key} title={message}
      className={`relative mx-1 ds-workspace-file-tree__row-pad h-[28px] truncate py-1 text-[12.5px] ${error ? 'text-red-600 dark:text-red-300' : 'text-ds-faint'}`}
      style={{ paddingLeft: indentPx(depth) }}>{guides}{message}</div>
    const entryKey = key
    const isDir = entry.kind === 'directory'
    const isDirty = dirtyKeys.has(entryKey)
    const isChanged = patchMap ? pathHasChanges(patchMap, entry.path) : false
    const dirHasChanges = isDir && patchMap ? directoryHasChanges(patchMap, entry.path) : false
    if (isDir) {
      return (
        <button
          key={entryKey}
          data-tree-key={entryKey}
          title={entry.path}
          type="button"
          aria-expanded={isExpanded}
          onClick={(event) => {
            event.preventDefault()
            event.stopPropagation()
            toggleDirectory(entry.path)
          }}
          className="ds-no-drag ds-workspace-file-tree__row ds-workspace-file-tree__row-pad flex h-[28px] w-full items-center gap-1.5 text-left text-[12.5px] text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
          style={{ paddingLeft: `${indentPx(depth)}px` }}
        >
          {guides}
          <ChevronRight
            className={`pointer-events-none h-3.5 w-3.5 shrink-0 text-ds-faint transition ${
              isExpanded ? 'rotate-90' : ''
            }`}
            strokeWidth={1.85}
            aria-hidden
          />
          {isExpanded ? <FolderOpen className="ds-tree-folder h-3.5 w-3.5 shrink-0" strokeWidth={1.6} aria-hidden /> : <Folder className="ds-tree-folder h-3.5 w-3.5 shrink-0" strokeWidth={1.6} aria-hidden />}
          <span className={`min-w-0 truncate ${dirHasChanges ? 'font-medium text-ds-ink' : ''}`}>
            {entry.name}
          </span>
        </button>
      )
    }

    const isActive = activeKeys.has(entryKey)
    const isFlashing = (flashPaths[entryKey] ?? 0) > Date.now()

    return (
      <button
        key={entryKey}
        data-tree-key={entryKey}
        type="button"
        draggable
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
          onOpenFile(entry.path)
        }}
        onDragStart={(event) => {
          setWorkspacePathDragData(event.dataTransfer, entry.path)
          // Drag ghost: same gray pill as the selected state (icon + name),
          // not the platform's full-row snapshot.
          const label = event.currentTarget.querySelector('.ds-workspace-file-tree__row-label')
          if (!label) return
          const ghost = document.createElement('div')
          ghost.className = 'ds-workspace-file-tree__drag-ghost'
          ghost.appendChild(label.cloneNode(true))
          document.body.appendChild(ghost)
          event.dataTransfer.setDragImage(ghost, 8, 14)
          event.currentTarget.addEventListener('dragend', () => ghost.remove(), { once: true })
        }}
        onContextMenu={(event) => {
          if (!onFileContextMenu) return
          event.preventDefault()
          event.stopPropagation()
          onFileContextMenu(event, entry.path)
        }}
        aria-current={isActive ? 'page' : undefined}
        className={`ds-no-drag ds-workspace-file-tree__row ds-workspace-file-tree__row-pad flex h-[28px] w-full items-center gap-1.5 text-left text-[12.5px] transition ${
          isFlashing ? 'ds-tree-row-flash' : ''
        } ${
          isActive
            ? 'ds-workspace-file-tree__row--active'
            : isDirty
              ? 'text-ds-ink hover:bg-ds-hover'
              : isChanged
                ? 'text-ds-ink'
                : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
        }`}
        style={{ paddingLeft: `${indentPx(depth) + (depth ? 6 : 20)}px` }}
        title={formatFilePathForDisplay(entry.path, trimmedRoot) ?? entry.path}
      >
        {guides}
        <span className="ds-workspace-file-tree__row-label flex min-w-0 items-center gap-1.5">
          <FileKindIcon path={entry.path} className="ds-file-kind-icon--chrome" />
          <span className="min-w-0 truncate">{entry.name}</span>
          {isDirty ? <span className="ds-tree-dirty-dot" aria-hidden /> : isChanged ? <span className="shrink-0 text-[11px] text-ds-muted" title={t('workspaceEditorChanged')}>•</span> : null}
        </span>
      </button>
    )
  }

  return (
    <div className="ds-no-drag ds-workspace-file-tree flex h-full min-h-0 flex-col overflow-hidden bg-ds-sidebar">
      <div className="ds-workspace-file-tree__header flex h-9 shrink-0 items-center gap-2 border-b border-[color-mix(in_srgb,var(--ds-text)_10%,transparent)]">
        {trimmedRoot ? (
          <>
            <Folder className="ds-tree-folder h-3.5 w-3.5 shrink-0" strokeWidth={1.6} aria-hidden />
            <div className="min-w-0 truncate text-[12.5px] font-medium text-ds-ink" title={trimmedRoot}>
              {workspaceLabel}
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-0.5">
              <Tooltip label={t('workspaceTreeShowAll')}>
                <button
                  type="button"
                  onClick={() => setShowAllFiles(!showAllFiles)}
                  aria-label={t('workspaceTreeShowAll')}
                  aria-pressed={showAllFiles}
                  className={`inline-flex h-6 w-6 items-center justify-center rounded-md transition hover:bg-ds-hover ${showAllFiles ? 'bg-ds-hover text-ds-ink' : 'text-ds-faint'}`}
                >
                  <Eye className="h-3.5 w-3.5" strokeWidth={1.85} aria-hidden />
                </button>
              </Tooltip>
              <Tooltip label={t('workspaceTreeRefresh')}>
                <button
                  type="button"
                  onClick={() => { void refreshLoadedDirectories() }}
                  aria-label={t('workspaceTreeRefresh')}
                  className="inline-flex h-6 w-6 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.94]"
                >
                  <RefreshCw
                    className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`}
                    strokeWidth={1.85}
                    aria-hidden
                  />
                </button>
              </Tooltip>
              <Tooltip label={anyExpanded ? t('workspaceTreeCollapseAll') : t('workspaceTreeExpandAll')}>
                <button
                  type="button"
                  onClick={anyExpanded ? collapseAll : () => { void scan(true) }}
                  aria-label={anyExpanded ? t('workspaceTreeCollapseAll') : t('workspaceTreeExpandAll')}
                  className="inline-flex h-6 w-6 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.94]"
                >
                  {anyExpanded ? (
                    <ChevronsDownUp className="h-3.5 w-3.5" strokeWidth={1.85} aria-hidden />
                  ) : (
                    <ChevronsUpDown className="h-3.5 w-3.5" strokeWidth={1.85} aria-hidden />
                  )}
                </button>
              </Tooltip>
            </div>
          </>
        ) : (
          <div className="text-[12.5px] leading-5 text-ds-faint">{t('workspaceTreeNoRoot')}</div>
        )}
      </div>
      <div ref={scrollRef} className="ds-workspace-file-tree__scroll min-h-0 flex-1 overflow-y-auto" style={{ overflowAnchor: 'none' }}
        onKeyDown={(event) => {
          if (!['ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'Tab'].includes(event.key)) return
          const key = (event.target as HTMLElement).closest<HTMLElement>('[data-tree-key]')?.dataset.treeKey
          if (!key) return
          const direction = event.key === 'ArrowUp' || event.key === 'End' || (event.key === 'Tab' && event.shiftKey) ? -1 : 1
          const current = rows.findIndex((row) => row.key === key)
          let index = event.key === 'Home' ? 0 : event.key === 'End' ? rows.length - 1
            : current + direction
          if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
            const item = rows[current]
            if (!item?.entry) return
            event.preventDefault()
            const right = event.key === 'ArrowRight'
            if (item.entry.kind === 'directory' && expanded.has(key) !== right) {
              toggleDirectory(item.entry.path)
              return
            }
            if (right) {
              if (!rows[index]?.entry || rows[index]!.depth <= item.depth) return
            } else {
              index = current - 1
              while (index >= 0 && rows[index]!.depth >= item.depth) index--
            }
          }
          while (index >= 0 && index < rows.length && !rows[index]!.entry) index += direction
          const row = rows[index]
          if (!row?.entry) return
          event.preventDefault()
          pendingFocus.current = row.key
          const top = Math.max(0, Math.min(index * rowHeight, Math.max(scrollTop, (index + 1) * rowHeight - viewport.height)))
          event.currentTarget.scrollTop = top
          setViewport((previous) => ({ ...previous, top }))
        }}
        onScroll={(event) => setViewport({ top: event.currentTarget.scrollTop, height: event.currentTarget.clientHeight || 560 })}>
        <div style={{ height: start * rowHeight }} aria-hidden />
        {rows.slice(start, end).map(renderRow)}
        <div style={{ height: (rows.length - end) * rowHeight }} aria-hidden />
      </div>
    </div>
  )
}
