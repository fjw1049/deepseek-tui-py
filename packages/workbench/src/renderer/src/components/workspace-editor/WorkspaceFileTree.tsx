import type { ReactElement } from 'react'
import { useEffect, useRef, useState } from 'react'
import { ChevronRight, FileCode2, Folder, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { WorkspaceTreeEntry } from '@shared/workspace-file'
import { formatFilePathForDisplay } from '../../lib/diff-stats'
import { directoryHasChanges, pathHasChanges } from '../../lib/workspace-change-patches'
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
  dirtyPaths?: Set<string>
  patchMap?: Map<string, string>
  onOpenFile: (path: string) => void
}

function normalizePath(path: string): string {
  return path.replace(/\\/g, '/')
}

function emptyNode(loading: boolean): TreeNodeState {
  return { entries: [], loading, loaded: false, error: null }
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

export function WorkspaceFileTree({ workspaceRoot, dirtyPaths, patchMap, onOpenFile }: Props): ReactElement {
  const { t } = useTranslation('common')
  const trimmedRoot = workspaceRoot.trim()
  const workspaceLabel = workspaceLabelFromPath(trimmedRoot) || trimmedRoot
  const trimmedRootRef = useRef(trimmedRoot)
  trimmedRootRef.current = trimmedRoot

  const [expanded, setExpanded] = useState<Set<string>>(() => new Set(['']))
  const [nodes, setNodes] = useState<Record<string, TreeNodeState>>({})

  useEffect(() => {
    let cancelled = false

    setExpanded(new Set(['']))
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
    })()

    return () => {
      cancelled = true
    }
  }, [trimmedRoot])

  const loadChildDirectory = (directoryPath: string): void => {
    const root = trimmedRootRef.current
    if (!root) return

    const key = normalizePath(directoryPath)
    setNodes((prev) => ({
      ...prev,
      [key]: emptyNode(true)
    }))

    void (async () => {
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
  }

  useEffect(() => {
    if (!patchMap || patchMap.size === 0) return

    const dirsToExpand = new Set<string>([''])
    for (const key of patchMap.keys()) {
      const parts = key.split('/').filter(Boolean)
      let acc = ''
      for (let i = 0; i < parts.length - 1; i += 1) {
        acc = acc ? `${acc}/${parts[i]}` : parts[i]!
        dirsToExpand.add(acc)
      }
    }

    setExpanded(dirsToExpand)
    for (const dir of dirsToExpand) {
      if (!dir) continue
      loadChildDirectory(dir)
    }
  }, [patchMap, trimmedRoot])

  const toggleDirectory = (path: string): void => {
    const key = normalizePath(path)
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
        const node = nodes[key]
        if (!node?.loaded && !node?.loading) {
          loadChildDirectory(path)
        }
      }
      return next
    })
  }

  const renderEntries = (directoryPath: string, depth: number): ReactElement[] => {
    const key = normalizePath(directoryPath)
    const node = nodes[key]

    if (!node) {
      return []
    }
    if (node.loading) {
      return [
        <div
          key={`${key}__loading`}
          className="flex items-center gap-2 px-2 py-1 text-[12px] text-ds-faint"
          style={{ paddingLeft: `${depth * 12 + 8}px` }}
        >
          <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={1.8} />
          {t('workspaceTreeLoading')}
        </div>
      ]
    }
    if (node.error) {
      return [
        <div
          key={`${key}__error`}
          className="px-2 py-1 text-[12px] text-red-600 dark:text-red-300"
          style={{ paddingLeft: `${depth * 12 + 8}px` }}
        >
          {node.error}
        </div>
      ]
    }

    if (node.loaded && node.entries.length === 0) {
      return [
        <div
          key={`${key}__empty`}
          className="px-2 py-1 text-[12px] text-ds-faint"
          style={{ paddingLeft: `${depth * 12 + 8}px` }}
        >
          {t('workspaceTreeEmpty')}
        </div>
      ]
    }

    return node.entries.flatMap((entry) => {
      const entryKey = normalizePath(entry.path)
      const isDir = entry.kind === 'directory'
      const isExpanded = expanded.has(entryKey)
      const isDirty = dirtyPaths?.has(entryKey)
      const isChanged = patchMap ? pathHasChanges(patchMap, entry.path) : false
      const dirHasChanges = isDir && patchMap ? directoryHasChanges(patchMap, entry.path) : false

      if (isDir) {
        return [
          <button
            key={entryKey}
            type="button"
            onClick={() => toggleDirectory(entry.path)}
            className="flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-[12.5px] text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink"
            style={{ paddingLeft: `${depth * 12 + 8}px` }}
          >
            <ChevronRight
              className={`h-3.5 w-3.5 shrink-0 transition ${isExpanded ? 'rotate-90' : ''}`}
              strokeWidth={1.85}
            />
            <Folder
              className={`h-3.5 w-3.5 shrink-0 ${dirHasChanges ? 'text-ds-diff-added' : 'text-ds-faint'}`}
              strokeWidth={1.85}
            />
            <span className={`truncate ${dirHasChanges ? 'font-medium text-ds-diff-added' : ''}`}>
              {entry.name}
            </span>
          </button>,
          ...(isExpanded ? renderEntries(entry.path, depth + 1) : [])
        ]
      }

      return [
        <button
          key={entryKey}
          type="button"
          onClick={() => onOpenFile(entry.path)}
          className={`flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-[12.5px] transition hover:bg-ds-hover/60 hover:text-ds-ink ${
            isDirty ? 'text-ds-ink' : isChanged ? 'text-ds-diff-added' : 'text-ds-muted'
          }`}
          style={{ paddingLeft: `${depth * 12 + 20}px` }}
          title={formatFilePathForDisplay(entry.path, trimmedRoot) ?? entry.path}
        >
          <FileCode2
            className={`h-3.5 w-3.5 shrink-0 ${isChanged ? 'text-ds-diff-added' : 'text-ds-faint'}`}
            strokeWidth={1.85}
          />
          <span className="truncate font-medium">{entry.name}</span>
          {isDirty ? <span className="ml-auto text-[10px] text-accent">●</span> : null}
        </button>
      ]
    })
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden border-r border-ds-border-muted/60 bg-ds-sidebar">
      <div className="shrink-0 border-b border-ds-border-muted/40 px-3 py-2">
        <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ds-faint">
          {t('workspaceTreeTitle')}
        </div>
        {trimmedRoot ? (
          <div className="mt-0.5 truncate text-[12px] font-medium text-ds-ink" title={trimmedRoot}>
            {workspaceLabel}
          </div>
        ) : (
          <div className="mt-1 text-[12px] leading-5 text-ds-faint">{t('workspaceTreeNoRoot')}</div>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto py-1">{renderEntries('', 0)}</div>
    </div>
  )
}
