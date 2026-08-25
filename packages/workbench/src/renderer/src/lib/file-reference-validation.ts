import { useEffect, useMemo, useState } from 'react'
import type { FileReferenceTarget } from './file-references'

type ValidationState =
  | { status: 'idle' }
  | { status: 'pending' }
  | { status: 'valid'; path: string; kind?: 'file' | 'directory' }
  | { status: 'invalid' }

type SettledValidation = Extract<ValidationState, { status: 'valid' | 'invalid' }>
type CachedValidation = SettledValidation | Promise<SettledValidation>

const validationCache = new Map<string, CachedValidation>()

function cacheKey(target: FileReferenceTarget | null, workspaceRoot?: string): string {
  return `${workspaceRoot?.trim() ?? ''}\u0000${target?.path ?? ''}`
}

async function validateFileReference(
  target: FileReferenceTarget,
  workspaceRoot?: string
): Promise<SettledValidation> {
  const key = cacheKey(target, workspaceRoot)
  const cached = validationCache.get(key)
  if (cached) return cached instanceof Promise ? cached : cached

  const task = (async (): Promise<SettledValidation> => {
    if (typeof window.dsGui?.resolveWorkspaceFile !== 'function') {
      return { status: 'invalid' }
    }

    const result = await window.dsGui.resolveWorkspaceFile({
      path: target.path,
      line: target.line,
      column: target.column,
      workspaceRoot
    })

    return result.ok
      ? { status: 'valid', path: result.path, kind: result.kind }
      : { status: 'invalid' }
  })()

  validationCache.set(key, task)
  try {
    const resolved = await task
    validationCache.set(key, resolved)
    return resolved
  } catch {
    const fallback = { status: 'invalid' } as const
    validationCache.set(key, fallback)
    return fallback
  }
}

export function useValidatedFileReference(
  target: FileReferenceTarget | null,
  workspaceRoot?: string
): ValidationState {
  const path = target?.path ?? ''
  const line = target?.line
  const column = target?.column
  const key = useMemo(
    () => cacheKey(path ? { path, line, column } : null, workspaceRoot),
    [column, line, path, workspaceRoot]
  )
  const [state, setState] = useState<ValidationState>(() => {
    if (!path) return { status: 'idle' }
    const cached = validationCache.get(key)
    if (!cached || cached instanceof Promise) return { status: 'pending' }
    return cached
  })

  useEffect(() => {
    if (!path) {
      setState((prev) => (prev.status === 'idle' ? prev : { status: 'idle' }))
      return
    }

    const cached = validationCache.get(key)
    if (cached && !(cached instanceof Promise)) {
      setState((prev) => (prev === cached ? prev : cached))
      return
    }

    let cancelled = false
    setState((prev) => (prev.status === 'pending' ? prev : { status: 'pending' }))
    void validateFileReference(
      {
        path,
        ...(line && line > 0 ? { line } : {}),
        ...(column && column > 0 ? { column } : {})
      },
      workspaceRoot
    ).then((next) => {
      if (!cancelled) setState(next)
    })

    return () => {
      cancelled = true
    }
  }, [column, key, line, path, workspaceRoot])

  return state
}
