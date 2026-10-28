import { useCallback, useEffect, useMemo, useState } from 'react'
import type { FileReferenceTarget } from './file-references'

export type FileReferenceCandidate = {
  path: string
  kind: 'file' | 'directory'
}

export type ValidationState =
  | { status: 'idle' }
  | { status: 'pending' }
  | { status: 'valid'; path: string; kind?: 'file' | 'directory' }
  | { status: 'ambiguous'; candidates: FileReferenceCandidate[]; message: string }
  | { status: 'invalid'; message: string }

type SettledValidation = Extract<ValidationState, { status: 'valid' | 'ambiguous' | 'invalid' }>
type CachedValidation = SettledValidation | Promise<SettledValidation>

const validationCache = new Map<string, CachedValidation>()

export function invalidateFileReferenceValidationCache(): void {
  validationCache.clear()
}

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
      return { status: 'invalid', message: 'File resolver is unavailable.' }
    }

    const result = await window.dsGui.resolveWorkspaceFile({
      path: target.path,
      line: target.line,
      column: target.column,
      workspaceRoot
    })

    if (result.ok) return { status: 'valid', path: result.path, kind: result.kind }
    if (result.code === 'ambiguous' && result.candidates?.length) {
      return {
        status: 'ambiguous',
        candidates: result.candidates,
        message: result.message
      }
    }
    return { status: 'invalid', message: result.message }
  })()

  validationCache.set(key, task)
  try {
    const resolved = await task
    validationCache.set(key, resolved)
    return resolved
  } catch {
    const fallback = { status: 'invalid', message: 'File resolution failed.' } as const
    validationCache.set(key, fallback)
    return fallback
  }
}

export function useValidatedFileReference(
  target: FileReferenceTarget | null,
  workspaceRoot?: string,
  revision = 0
): { validation: ValidationState; retry: () => void } {
  const path = target?.path ?? ''
  const line = target?.line
  const column = target?.column
  const key = useMemo(
    () => cacheKey(path ? { path, line, column } : null, workspaceRoot),
    [column, line, path, workspaceRoot]
  )
  const [state, setState] = useState<{ key: string; validation: ValidationState }>(() => {
    if (!path) return { key, validation: { status: 'idle' } }
    const cached = validationCache.get(key)
    if (!cached || cached instanceof Promise) return { key, validation: { status: 'pending' } }
    return { key, validation: cached }
  })
  const [retryToken, setRetryToken] = useState(0)
  const retry = useCallback(() => {
    validationCache.delete(key)
    setRetryToken((value) => value + 1)
  }, [key])

  useEffect(() => {
    if (!path) {
      setState((prev) => (prev.key === key && prev.validation.status === 'idle' ? prev : { key, validation: { status: 'idle' } }))
      return
    }

    const cached = validationCache.get(key)
    if (cached && !(cached instanceof Promise)) {
      setState((prev) => (prev.key === key && prev.validation === cached ? prev : { key, validation: cached }))
      return
    }

    let cancelled = false
    // Keep the same target visible while checking for filesystem changes.
    setState((prev) => (prev.key === key ? prev : { key, validation: { status: 'pending' } }))
    void validateFileReference(
      {
        path,
        ...(line && line > 0 ? { line } : {}),
        ...(column && column > 0 ? { column } : {})
      },
      workspaceRoot
    ).then((next) => {
      if (!cancelled) setState({ key, validation: next })
    })

    return () => {
      cancelled = true
    }
  }, [column, key, line, path, retryToken, revision, workspaceRoot])

  const validation: ValidationState = state.key === key
    ? state.validation
    : { status: path ? 'pending' : 'idle' }
  return { validation, retry }
}
