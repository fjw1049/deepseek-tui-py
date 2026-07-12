// Single source of truth for the default (Chats / temporary) workspace root.
//
// This path plays two roles that MUST stay in sync:
//   1. the default/fallback workspace a brand-new temporary chat lands in, and
//   2. the sentinel used to detect "this is the default workspace" for labels
//      and new-thread branching (inherit project vs. open a temporary chat).
//
// To relocate the default workspace, change ONLY `DEFAULT_WORKSPACE_SEGMENTS`.
// Everything else (tilde form, suffix match, detection) derives from it.

/** Path segments under the home directory, e.g. `~/.deepseek/workspace`. */
export const DEFAULT_WORKSPACE_SEGMENTS = ['.deepseek', 'workspace'] as const

/** Tilde form used by the renderer + settings default (main expands "~"). */
export const DEFAULT_WORKSPACE_ROOT = `~/${DEFAULT_WORKSPACE_SEGMENTS.join('/')}`

/** Suffix used to detect the default workspace regardless of `~` vs absolute. */
export const DEFAULT_WORKSPACE_PATH_SUFFIX = `/${DEFAULT_WORKSPACE_SEGMENTS.join('/')}`

// Legacy default-workspace locations from earlier builds. Kept so threads
// created before the default moved are still treated as Chats (correct label
// + new-thread branching). New threads never use these.
const LEGACY_WORKSPACE_PATH_SUFFIXES = ['/.deepseekgui/default_workspace']

function normalizePathForMatch(path: string): string {
  return path.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

/**
 * True when `path` points at the default (Chats/temporary) workspace root,
 * whether expressed as `~/…` or an absolute home path. Also matches legacy
 * default locations so pre-existing threads keep their Chats behavior.
 */
export function isDefaultWorkspaceRoot(path?: string): boolean {
  const trimmed = path?.trim() ?? ''
  if (!trimmed) return false
  const normalized = normalizePathForMatch(trimmed)
  if (normalized === DEFAULT_WORKSPACE_ROOT.toLowerCase()) return true
  if (normalized.endsWith(DEFAULT_WORKSPACE_PATH_SUFFIX)) return true
  return LEGACY_WORKSPACE_PATH_SUFFIXES.some((suffix) => normalized.endsWith(suffix))
}
