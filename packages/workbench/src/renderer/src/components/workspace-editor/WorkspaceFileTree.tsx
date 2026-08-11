import type { MouseEvent as ReactMouseEvent, ReactElement } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ChevronRight,
  File,
  FileCode2,
  FileJson,
  FileText,
  Folder,
  FolderOpen,
  Image as ImageIcon,
  Loader2
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { WorkspaceTreeEntry } from '@shared/workspace-file'
import { formatFilePathForDisplay } from '../../lib/diff-stats'
import { directoryHasChanges, pathHasChanges } from '../../lib/workspace-change-patches'
import {
  readExpandedDirs,
  writeExpandedDirs
} from '../../lib/workspace-file-tree-expand-cache'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import i18n from '../../i18n'

type TreeNodeState = {
  entries: WorkspaceTreeEntry[]
  loading: boolean
  loaded: boolean
  error: string | null
}

type Props = {
  workspaceRoot: string
  activePaths?: string[]
  dirtyPaths?: Set<string>
  patchMap?: Map<string, string>
  onOpenFile: (path: string) => void
  onFileContextMenu?: (event: ReactMouseEvent, path: string) => void
}

/** Tree keys: posix + lower-case so clicks and cache always agree. */
function treeKey(path: string): string {
  return path.replace(/\\/g, '/').replace(/^\/+/, '').trim().toLowerCase()
}

function emptyNode(loading: boolean): TreeNodeState {
  return { entries: [], loading, loaded: false, error: null }
}

function fileIconForName(name: string): typeof FileCode2 {
  const lower = name.toLowerCase()
  if (/\.(png|jpe?g|gif|webp|svg|ico|bmp)$/.test(lower)) return ImageIcon
  if (/\.(json|jsonc|json5)$/.test(lower)) return FileJson
  if (/\.(md|txt|rst|log)$/.test(lower)) return FileText
  if (/\.(tsx?|jsx?|mjs|cjs|py|go|rs|java|kt|swift|rb|php|css|scss|less|html?|vue|svelte|toml|ya?ml|sh|bash|zsh|c|cc|cpp|h|hpp)$/.test(lower)) {
    return FileCode2
  }
  return File
}

async function fetchDirectory(
  workspaceRoot: string,
  directoryPath: string
): Promise<{ ok: true; entries: WorkspaceTreeEntry[] } | { ok: false; message: string }> {
  if (typeof window.dsGui?.listWorkspaceDirectory !== 'function') {
    return { ok: false, message: 'workspaceTreeUnavailable' }
  }

  try {
    const result = await window.dsGui.listWorkspaceDirectory(workspaceRoot, directoryPath)
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
  return depth * 12 + 8
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
  onOpenFile,
  onFileContextMenu
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const trimmedRoot = workspaceRoot.trim()
  const workspaceLabel = workspaceLabelFromPath(trimmedRoot) || trimmedRoot
  const activeKeys = new Set((activePaths ?? []).map(treeKey).filter(Boolean))
  const trimmedRootRef = useRef(trimmedRoot)
  trimmedRootRef.current = trimmedRoot
  const nodesRef = useRef<Record<string, TreeNodeState>>({})

  const [expanded, setExpanded] = useState<Set<string>>(() => {
    const restored = readExpandedDirs(trimmedRoot)
    return new Set([...restored].map(treeKey))
  })
  const [nodes, setNodes] = useState<Record<string, TreeNodeState>>({})
  nodesRef.current = nodes

  const loadChildDirectory = useCallback((directoryPath: string): void => {
    const root = trimmedRootRef.current
    if (!root) return

    const key = treeKey(directoryPath)
    const existing = nodesRef.current[key]
    if (existing?.loading || existing?.loaded) return

    setNodes((prev) => ({
      ...prev,
      [key]: emptyNode(true)
    }))

    void (async () => {
      // Prefer the original relative path for IPC; key is only for state.
      const result = await fetchDirectory(root, directoryPath)
      if (trimmedRootRef.current !== root) return

      setNodes((prev) => ({
        ...prev,
        [key]: {
          entries: result.ok ? result.entries : [],
          loading: false,
          loaded: true,
          error: result.ok ? null : translateTreeError(result.message)
        }
      }))
    })()
  }, [])

  useEffect(() => {
    let cancelled = false
    const restored = new Set([...readExpandedDirs(trimmedRoot)].map(treeKey))
    setExpanded(restored)

    if (!trimmedRoot) {
      setNodes({})
      return () => {
        cancelled = true
      }
    }

    setNodes({ '': emptyNode(true) })

    void (async () => {
      const result = await fetchDirectory(trimmedRoot, '')
      if (cancelled || trimmedRootRef.current !== trimmedRoot) return

      setNodes({
        '': {
          entries: result.ok ? result.entries : [],
          loading: false,
          loaded: true,
          error: result.ok ? null : translateTreeError(result.message)
        }
      })

      for (const dir of restored) {
        if (!dir) continue
        loadChildDirectory(dir)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [trimmedRoot, loadChildDirectory])

  // When the active editor file changes, reveal its ancestors once (VS Code).
  // Do NOT expand every dirty path on git/patch refresh — that fights folder clicks.
  const lastRevealedActiveRef = useRef('')
  useEffect(() => {
    const active = (activePaths ?? []).map(treeKey).find(Boolean)
    if (!active || active === lastRevealedActiveRef.current) return
    lastRevealedActiveRef.current = active

    const parts = active.split('/').filter(Boolean)
    const ancestors: string[] = []
    let acc = ''
    for (let i = 0; i < parts.length - 1; i += 1) {
      acc = acc ? `${acc}/${parts[i]}` : parts[i]!
      ancestors.push(acc)
    }
    if (ancestors.length === 0) return

    setExpanded((prev) => {
      const next = new Set(prev)
      for (const dir of ancestors) next.add(dir)
      writeExpandedDirs(trimmedRoot, next)
      return next
    })
    for (const dir of ancestors) {
      loadChildDirectory(dir)
    }
  }, [activePaths, loadChildDirectory, trimmedRoot])

  const toggleDirectory = useCallback(
    (path: string): void => {
      const key = treeKey(path)
      setExpanded((prev) => {
        const next = new Set(prev)
        const willExpand = !next.has(key)
        if (willExpand) {
          next.add(key)
        } else {
          next.delete(key)
        }
        writeExpandedDirs(trimmedRootRef.current, next)
        if (willExpand) {
          const node = nodesRef.current[key]
          if (!node?.loaded && !node?.loading) {
            queueMicrotask(() => loadChildDirectory(path))
          }
        }
        return next
      })
    },
    [loadChildDirectory]
  )

  const renderEntries = (directoryPath: string, depth: number): ReactElement[] => {
    const key = treeKey(directoryPath)
    const node = nodes[key]

    if (!node) {
      return []
    }
    if (node.loading) {
      return [
        <div
          key={`${key}__loading`}
          className="ds-workspace-file-tree__row-pad flex h-7 items-center gap-1.5 text-[12px] text-ds-faint"
          style={{ paddingLeft: `${indentPx(depth)}px` }}
        >
          <Loader2 className="pointer-events-none h-3.5 w-3.5 animate-spin" strokeWidth={1.8} />
          {t('workspaceTreeLoading')}
        </div>
      ]
    }
    if (node.error) {
      return [
        <div
          key={`${key}__error`}
          className="ds-workspace-file-tree__row-pad py-1 text-[12px] text-red-600 dark:text-red-300"
          style={{ paddingLeft: `${indentPx(depth)}px` }}
        >
          {node.error}
        </div>
      ]
    }

    if (node.loaded && node.entries.length === 0) {
      return [
        <div
          key={`${key}__empty`}
          className="ds-workspace-file-tree__row-pad py-1 text-[12px] text-ds-faint"
          style={{ paddingLeft: `${indentPx(depth)}px` }}
        >
          {t('workspaceTreeEmpty')}
        </div>
      ]
    }

    return node.entries.flatMap((entry) => {
      const entryKey = treeKey(entry.path)
      const isDir = entry.kind === 'directory'
      const isExpanded = expanded.has(entryKey)
      const isDirty = dirtyPaths
        ? [...dirtyPaths].some((p) => treeKey(p) === entryKey)
        : false
      const isChanged = patchMap ? pathHasChanges(patchMap, entry.path) : false
      const dirHasChanges = isDir && patchMap ? directoryHasChanges(patchMap, entry.path) : false

      if (isDir) {
        const FolderIcon = isExpanded ? FolderOpen : Folder
        return [
          <button
            key={entryKey}
            type="button"
            aria-expanded={isExpanded}
            onClick={(event) => {
              event.preventDefault()
              event.stopPropagation()
              toggleDirectory(entry.path)
            }}
            className="ds-no-drag ds-workspace-file-tree__row ds-workspace-file-tree__row-pad flex h-7 w-full items-center gap-1.5 text-left text-[12px] text-ds-muted transition hover:bg-ds-hover/55 hover:text-ds-ink"
            style={{ paddingLeft: `${indentPx(depth)}px` }}
          >
            <ChevronRight
              className={`pointer-events-none h-3.5 w-3.5 shrink-0 opacity-75 transition ${
                isExpanded ? 'rotate-90' : ''
              }`}
              strokeWidth={1.85}
            />
            <FolderIcon
              className={`pointer-events-none h-3.5 w-3.5 shrink-0 ${
                dirHasChanges ? 'text-ds-diff-added' : 'text-ds-faint'
              }`}
              strokeWidth={1.85}
            />
            <span className={`min-w-0 truncate ${dirHasChanges ? 'font-medium text-ds-diff-added' : ''}`}>
              {entry.name}
            </span>
          </button>,
          ...(isExpanded ? renderEntries(entry.path, depth + 1) : [])
        ]
      }

      const isActive = activeKeys.has(entryKey)
      const FileIcon = fileIconForName(entry.name)

      return [
        <button
          key={entryKey}
          type="button"
          onClick={(event) => {
            event.preventDefault()
            event.stopPropagation()
            onOpenFile(entry.path)
          }}
          onContextMenu={(event) => {
            if (!onFileContextMenu) return
            event.preventDefault()
            event.stopPropagation()
            onFileContextMenu(event, entry.path)
          }}
          aria-current={isActive ? 'page' : undefined}
          className={`ds-no-drag ds-workspace-file-tree__row ds-workspace-file-tree__row-pad flex h-7 w-full items-center gap-1.5 text-left text-[12px] transition ${
            isActive
              ? 'ds-workspace-file-tree__row--active'
              : isDirty
                ? 'text-ds-ink hover:bg-ds-hover/55'
                : isChanged
                  ? 'text-ds-diff-added hover:bg-ds-hover/55 hover:text-ds-ink'
                  : 'text-ds-muted hover:bg-ds-hover/55 hover:text-ds-ink'
          }`}
          style={{ paddingLeft: `${indentPx(depth) + 14}px` }}
          title={formatFilePathForDisplay(entry.path, trimmedRoot) ?? entry.path}
        >
          <FileIcon
            className={`pointer-events-none h-3.5 w-3.5 shrink-0 opacity-80 ${
              isActive ? 'text-current' : isChanged ? 'text-ds-diff-added' : 'text-ds-faint'
            }`}
            strokeWidth={isActive ? 2.05 : 1.85}
          />
          <span className="min-w-0 truncate">{entry.name}</span>
          {isDirty ? <span className="ml-auto text-[10px] text-accent">●</span> : null}
        </button>
      ]
    })
  }

  return (
    <div className="ds-no-drag ds-workspace-file-tree flex h-full min-h-0 flex-col overflow-hidden bg-ds-sidebar">
      <div className="ds-workspace-file-tree__header flex h-10 shrink-0 items-center gap-2 border-b border-[color-mix(in_srgb,var(--ds-text)_10%,transparent)]">
        {trimmedRoot ? (
          <>
            <Folder className="pointer-events-none h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.85} />
            <div className="min-w-0 truncate text-[12px] font-semibold text-ds-ink" title={trimmedRoot}>
              {workspaceLabel}
            </div>
          </>
        ) : (
          <div className="text-[12px] leading-5 text-ds-faint">{t('workspaceTreeNoRoot')}</div>
        )}
      </div>
      <div className="ds-workspace-file-tree__scroll min-h-0 flex-1 overflow-y-auto py-1">
        {renderEntries('', 0)}
      </div>
    </div>
  )
}
