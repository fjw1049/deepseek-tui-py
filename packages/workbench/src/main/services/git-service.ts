import { execFile } from 'node:child_process'
import { realpath, stat } from 'node:fs/promises'
import { join, resolve } from 'node:path'
import { promisify } from 'node:util'
import type { GitCommitMessageSuggestionResult, GitCommitResult } from '../../shared/git-commit'
import type { GitLogCommit, GitLogResult, GitLogUpstream } from '../../shared/git-log'
import type { GitBranchesResult } from '../../shared/git-branches'
import type { GitPathActionResult, GitPullResult, GitPushResult } from '../../shared/git-actions'
import type {
  GitChangeScope,
  GitWorkingChangeFile,
  GitWorkingChangeStage,
  GitWorkingChangeStatus,
  GitWorkingChangesResult
} from '../../shared/git-working-changes'
import {
  parseGitRemoteRepository,
  type GitHubRepositoryResult
} from '../../shared/github-repository'

const execFileAsync = promisify(execFile)
const DIFF_MAX_BUFFER = 50 * 1024 * 1024

async function runGit(
  cwd: string,
  args: string[],
  timeout = 10_000,
  maxBuffer = 1024 * 1024
): Promise<{ stdout: string; stderr: string }> {
  const { stdout, stderr } = await execFileAsync('git', args, {
    cwd,
    timeout,
    maxBuffer,
    env: { ...process.env, GIT_TERMINAL_PROMPT: '0' }
  })
  return { stdout: String(stdout), stderr: String(stderr) }
}

async function runGitStdout(
  cwd: string,
  args: string[],
  options?: { timeout?: number; maxBuffer?: number; allowNonZero?: boolean }
): Promise<string> {
  const timeout = options?.timeout ?? 10_000
  const maxBuffer = options?.maxBuffer ?? 1024 * 1024
  try {
    const { stdout } = await execFileAsync('git', args, { cwd, timeout, maxBuffer })
    return String(stdout)
  } catch (error) {
    if (options?.allowNonZero && error && typeof error === 'object' && 'stdout' in error) {
      return String((error as { stdout: unknown }).stdout ?? '')
    }
    throw error
  }
}

function gitFailure(error: unknown): GitBranchesResult {
  const message = error instanceof Error ? error.message : String(error)
  if (/not a git repository/i.test(message)) {
    return { ok: false, reason: 'not_git_repo', message: 'The working directory is not a Git repository.' }
  }
  if (/ENOENT/i.test(message) || /spawn git/i.test(message)) {
    return { ok: false, reason: 'git_unavailable', message: 'Git executable was not found.' }
  }
  return { ok: false, reason: 'error', message }
}

const RUNTIME_CHECKOUT_MESSAGE =
  'The development app is running from this checkout. Use an installed build or a separate checkout before switching branches.'

function normalizeCheckoutPath(path: string): string {
  const normalized = resolve(path)
  return process.platform === 'win32' ? normalized.toLowerCase() : normalized
}

async function protectRuntimeCheckout(cwd: string): Promise<GitBranchesResult | null> {
  const rendererUrl = process.env.ELECTRON_RENDERER_URL?.trim()
  const runtimeRoot = process.env.DEEPSEEK_REPO_ROOT?.trim()
  if (!rendererUrl || !runtimeRoot) return null

  try {
    const [workspaceResult, runtimeResult] = await Promise.all([
      runGit(cwd, ['rev-parse', '--show-toplevel']),
      runGit(runtimeRoot, ['rev-parse', '--show-toplevel'])
    ])
    const [workspaceRoot, runtimeCheckoutRoot] = await Promise.all([
      realpath(workspaceResult.stdout.trim()),
      realpath(runtimeResult.stdout.trim())
    ])
    if (normalizeCheckoutPath(workspaceRoot) === normalizeCheckoutPath(runtimeCheckoutRoot)) {
      return { ok: false, reason: 'runtime_checkout', message: RUNTIME_CHECKOUT_MESSAGE }
    }
  } catch {
    // Let the requested Git operation report invalid paths or unavailable Git.
  }
  return null
}

function gitWorkingChangesFailure(error: unknown): GitWorkingChangesResult {
  const message = error instanceof Error ? error.message : String(error)
  if (/not a git repository/i.test(message)) {
    return { ok: false, reason: 'not_git_repo', message: 'The working directory is not a Git repository.' }
  }
  if (/ENOENT/i.test(message) || /spawn git/i.test(message)) {
    return { ok: false, reason: 'git_unavailable', message: 'Git executable was not found.' }
  }
  return { ok: false, reason: 'error', message }
}

function unquoteGitPath(raw: string): string {
  const trimmed = raw.trim()
  if (trimmed.startsWith('"') && trimmed.endsWith('"')) {
    return trimmed
      .slice(1, -1)
      .replace(/\\(["\\])/g, '$1')
  }
  return trimmed
}

function resolveGitStage(indexStatus: string, workTreeStatus: string): GitWorkingChangeStage {
  const indexDirty = indexStatus !== ' ' && indexStatus !== '?'
  const workTreeDirty = workTreeStatus !== ' ' && workTreeStatus !== '?'
  if (indexDirty && workTreeDirty) return 'partial'
  if (indexDirty) return 'staged'
  return 'unstaged'
}

function parsePorcelainEntry(
  line: string
): {
  path: string
  status: GitWorkingChangeStatus
  stage: GitWorkingChangeStage
  indexStatus: string
  workTreeStatus: string
} | null {
  if (line.length < 4) return null

  const indexStatus = line[0] ?? ' '
  const workTreeStatus = line[1] ?? ' '
  let pathPart = unquoteGitPath(line.slice(3))
  if (!pathPart) return null

  if (pathPart.includes(' -> ')) {
    const parts = pathPart.split(' -> ')
    pathPart = unquoteGitPath(parts[parts.length - 1] ?? pathPart)
  }

  const statusKey = `${indexStatus}${workTreeStatus}`
  let status: GitWorkingChangeStatus = 'modified'
  if (statusKey === '??') status = 'untracked'
  else if (indexStatus === 'A' || workTreeStatus === 'A') status = 'added'
  else if (indexStatus === 'D' || workTreeStatus === 'D') status = 'deleted'
  else if (indexStatus === 'R' || workTreeStatus === 'R') status = 'renamed'
  else if (indexStatus === 'C' || workTreeStatus === 'C') status = 'copied'

  return {
    path: pathPart,
    status,
    stage: resolveGitStage(indexStatus, workTreeStatus),
    indexStatus,
    workTreeStatus
  }
}

function gitStatusFromCode(code: string, fallback: GitWorkingChangeStatus): GitWorkingChangeStatus {
  if (code === 'A' || code === '?') return code === '?' ? 'untracked' : 'added'
  if (code === 'D') return 'deleted'
  if (code === 'R') return 'renamed'
  if (code === 'C') return 'copied'
  if (code === 'M' || code === 'T' || code === 'U') return 'modified'
  return fallback
}

function splitUnifiedDiff(patch: string): Map<string, string> {
  const byPath = new Map<string, string>()
  const trimmed = patch.trim()
  if (!trimmed) return byPath

  const chunks = trimmed.split(/^diff --git /m).filter(Boolean)
  for (const chunk of chunks) {
    const fullPatch = `diff --git ${chunk}`.trimEnd()
    const header = fullPatch.split('\n')[0] ?? ''
    const match = header.match(/ b\/(.+)$/)
    const path = match?.[1]?.trim()
    if (!path) continue
    byPath.set(path, fullPatch)
  }

  return byPath
}

type LocalBranchRef = { name: string; commit: string }

async function listLocalBranches(cwd: string, mergedIntoHead = false): Promise<LocalBranchRef[]> {
  const args = [
    'for-each-ref',
    '--sort=-committerdate',
    '--format=%(refname:short)\t%(objectname)'
  ]
  if (mergedIntoHead) args.push('--merged=HEAD')
  args.push('refs/heads')
  return (await runGit(cwd, args)).stdout
    .split('\n')
    .map((line) => {
      const [name = '', commit = ''] = line.trim().split('\t')
      return { name, commit }
    })
    .filter((branch) => branch.name && branch.commit)
}

async function resolveCurrentBranch(cwd: string): Promise<string | null> {
  const direct = (await runGit(cwd, ['branch', '--show-current'])).stdout.trim()
  if (direct) return direct

  // Managed task worktrees use detached HEAD. The nearest recently active
  // local ancestor is the branch the task was started from.
  const merged = await listLocalBranches(cwd, true)
  return merged[0]?.name ?? null
}

async function resolveRepositoryDefaultBranch(cwd: string): Promise<string | null> {
  let upstream = ''
  try {
    upstream = (
      await runGit(cwd, ['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}'])
    ).stdout.trim()
  } catch {
    // A local-only branch may not have an upstream.
  }

  const upstreamRemote = upstream.includes('/') ? upstream.split('/')[0] : ''
  const candidates: string[] = []
  for (const remote of [...new Set([upstreamRemote, 'origin'].filter(Boolean))]) {
    try {
      const remoteDefault = (
        await runGit(cwd, [
          'symbolic-ref',
          '--quiet',
          '--short',
          `refs/remotes/${remote}/HEAD`
        ])
      ).stdout.trim()
      if (remoteDefault) candidates.push(remoteDefault)
    } catch {
      // A remote HEAD symbolic ref is optional.
    }
  }
  candidates.push('origin/main', 'origin/master', 'main', 'master')

  for (const candidate of [...new Set(candidates)]) {
    try {
      await runGit(cwd, ['rev-parse', '--verify', '--quiet', `${candidate}^{commit}`])
      return candidate
    } catch {
      // Try the next conventional default ref.
    }
  }
  return null
}

async function resolveRecentAncestorBranch(
  cwd: string,
  currentBranch: string | null,
  defaultBranch: string | null
): Promise<string | null> {
  if (!currentBranch) return null
  const defaultLocalName = defaultBranch?.includes('/')
    ? defaultBranch.slice(defaultBranch.indexOf('/') + 1)
    : defaultBranch
  if (currentBranch === defaultLocalName) return null

  const headCommit = (await runGit(cwd, ['rev-parse', 'HEAD'])).stdout.trim()
  const merged = await listLocalBranches(cwd, true)
  const recent = merged.find(
    (branch) => branch.name !== currentBranch && branch.commit !== headCommit
  )?.name
  return recent === defaultLocalName ? defaultBranch : (recent ?? null)
}

async function readGitRemoteState(
  cwd: string,
  refreshRemote: boolean
): Promise<{
  hasRemote: boolean
  refreshError: string | null
  refreshedAt: string | null
}> {
  const remotes = (await runGit(cwd, ['remote'])).stdout
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (!refreshRemote || remotes.length === 0) {
    return { hasRemote: remotes.length > 0, refreshError: null, refreshedAt: null }
  }
  try {
    await runGit(cwd, ['fetch', '--prune'], 120_000, DIFF_MAX_BUFFER)
    return { hasRemote: true, refreshError: null, refreshedAt: new Date().toISOString() }
  } catch (error) {
    return {
      hasRemote: true,
      refreshError: error instanceof Error ? error.message : String(error),
      refreshedAt: null
    }
  }
}

export async function getGitBranches(
  workspaceRoot: string,
  refreshRemote = false
): Promise<GitBranchesResult> {
  const cwd = workspaceRoot.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }
  try {
    const repositoryRoot = (await runGit(cwd, ['rev-parse', '--show-toplevel'])).stdout.trim()
    const remote = await readGitRemoteState(cwd, refreshRemote)
    const attachedBranch = (await runGit(cwd, ['branch', '--show-current'])).stdout.trim()
    const currentBranch = attachedBranch || null
    const inferredBranch = currentBranch ? null : await resolveCurrentBranch(cwd)
    const branchForComparison = currentBranch ?? inferredBranch
    const localBranches = await listLocalBranches(cwd)
    const branches = localBranches.map(({ name }) => ({ name, current: currentBranch === name }))
    const defaultBranch = await resolveRepositoryDefaultBranch(cwd)
    const recommendedBase =
      (await resolveRecentAncestorBranch(cwd, branchForComparison, defaultBranch)) ?? defaultBranch
    const dirtyCount = (await runGit(cwd, ['status', '--porcelain=v1'])).stdout
      .split('\n')
      .filter((line) => line.trim().length > 0).length
    let upstream: string | null = null
    let ahead = 0
    let behind = 0
    if (currentBranch) {
      try {
        upstream = (
          await runGit(cwd, ['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}'])
        ).stdout.trim() || null
      } catch {
        upstream = null
      }
      if (upstream) {
        try {
          const counts = (await runGit(cwd, ['rev-list', '--left-right', '--count', `HEAD...${upstream}`]))
            .stdout.trim()
            .split(/\s+/)
          ahead = Number.parseInt(counts[0] ?? '0', 10) || 0
          behind = Number.parseInt(counts[1] ?? '0', 10) || 0
        } catch {
          ahead = 0
          behind = 0
        }
      }
    }
    return {
      ok: true,
      repositoryRoot,
      currentBranch,
      detached: !currentBranch,
      inferredBranch,
      branches,
      defaultBranch,
      recommendedBase,
      dirtyCount,
      upstream,
      ahead,
      behind,
      hasRemote: remote.hasRemote,
      remoteRefreshError: remote.refreshError
    }
  } catch (error) {
    return gitFailure(error)
  }
}

function isDirtyWorktreeError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error)
  return (
    /would be overwritten by (checkout|merge)/i.test(message) ||
    /commit your changes or stash them/i.test(message)
  )
}

export async function switchGitBranch(
  workspaceRoot: string,
  branchName: string
): Promise<GitBranchesResult> {
  const cwd = workspaceRoot.trim()
  const branch = branchName.trim()
  if (!cwd) return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  if (!branch) return { ok: false, reason: 'error', message: 'Branch name is required.' }
  const runtimeCheckoutFailure = await protectRuntimeCheckout(cwd)
  if (runtimeCheckoutFailure) return runtimeCheckoutFailure
  try {
    try {
      await runGit(cwd, ['switch', branch], 20_000)
    } catch (switchError) {
      if (isDirtyWorktreeError(switchError)) throw switchError
      await runGit(cwd, ['checkout', branch], 20_000)
    }
    return getGitBranches(cwd)
  } catch (error) {
    if (isDirtyWorktreeError(error)) {
      return {
        ok: false,
        reason: 'dirty_worktree',
        message: error instanceof Error ? error.message : String(error)
      }
    }
    return gitFailure(error)
  }
}

export async function stashAndSwitchGitBranch(
  workspaceRoot: string,
  branchName: string
): Promise<GitBranchesResult> {
  const cwd = workspaceRoot.trim()
  const branch = branchName.trim()
  if (!cwd) return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  if (!branch) return { ok: false, reason: 'error', message: 'Branch name is required.' }
  const runtimeCheckoutFailure = await protectRuntimeCheckout(cwd)
  if (runtimeCheckoutFailure) return runtimeCheckoutFailure
  try {
    const stashMessage = `workbench: auto stash before switching to ${branch}`
    const pushResult = await runGit(
      cwd,
      ['stash', 'push', '--include-untracked', '-m', stashMessage],
      30_000
    )
    const stashed = !/No local changes to save/i.test(pushResult.stdout)

    try {
      try {
        await runGit(cwd, ['switch', branch], 20_000)
      } catch {
        await runGit(cwd, ['checkout', branch], 20_000)
      }
    } catch (switchError) {
      // Restore the user's changes on the original branch before reporting.
      if (stashed) {
        try {
          await runGit(cwd, ['stash', 'pop'], 30_000)
        } catch {
          // Leave the stash in place; it is still recoverable via `git stash pop`.
        }
      }
      throw switchError
    }

    if (stashed) {
      try {
        await runGit(cwd, ['stash', 'pop'], 30_000)
      } catch (popError) {
        return {
          ok: false,
          reason: 'stash_pop_conflict',
          message: popError instanceof Error ? popError.message : String(popError)
        }
      }
    }

    return getGitBranches(cwd)
  } catch (error) {
    return gitFailure(error)
  }
}

// Result cache for getGitWorkingChanges keyed by workspace root + review scope.
// Diff generation can be expensive on large repos; a cheap fingerprint detects
// when neither HEAD, the index, nor changed files moved.
const workingChangesCache = new Map<string, { fingerprint: string; result: GitWorkingChangesResult }>()
const WORKING_CHANGES_CACHE_MAX_ROOTS = 24

function invalidateWorkingChangesCache(cwd: string): void {
  const prefix = `${cwd}\u0000`
  for (const key of workingChangesCache.keys()) {
    if (key.startsWith(prefix)) workingChangesCache.delete(key)
  }
}

async function workingChangesFingerprint(
  cwd: string,
  repositoryRoot: string,
  porcelainLines: string[],
  paths: string[]
): Promise<string> {
  let head = ''
  try {
    head = (await runGit(cwd, ['rev-parse', 'HEAD'])).stdout.trim()
  } catch {
    // Repo without commits — porcelain output still fingerprints the state.
  }
  const stats = await Promise.all(
    paths.map(async (path) => {
      try {
        const s = await stat(join(repositoryRoot, path))
        return `${path}\u0000${s.mtimeMs}\u0000${s.size}`
      } catch {
        return `${path}\u0000absent`
      }
    })
  )
  return [head, porcelainLines.join('\n'), stats.join('\u0001')].join('\u0002')
}

type ParsedPorcelainEntry = NonNullable<ReturnType<typeof parsePorcelainEntry>>

async function untrackedPatch(cwd: string, path: string): Promise<string> {
  return runGitStdout(cwd, ['diff', '--no-index', '--no-color', '/dev/null', path], {
    timeout: 20_000,
    maxBuffer: DIFF_MAX_BUFFER,
    allowNonZero: true
  })
}

async function buildLayerFiles(
  cwd: string,
  entries: ParsedPorcelainEntry[],
  layer: 'staged' | 'unstaged'
): Promise<GitWorkingChangeFile[]> {
  const selected = entries.filter((entry) =>
    layer === 'staged'
      ? entry.indexStatus !== ' ' && entry.indexStatus !== '?'
      : entry.workTreeStatus !== ' ' || entry.status === 'untracked'
  )
  if (selected.length === 0) return []

  const args = layer === 'staged' ? ['diff', '--cached', '--no-color'] : ['diff', '--no-color']
  const allPatch = await runGitStdout(cwd, args, {
    timeout: 30_000,
    maxBuffer: DIFF_MAX_BUFFER,
    allowNonZero: true
  })
  const patchByPath = splitUnifiedDiff(allPatch)
  const files: GitWorkingChangeFile[] = []

  for (const entry of selected) {
    let patch = ''
    try {
      if (layer === 'unstaged' && entry.status === 'untracked') {
        patch = await untrackedPatch(cwd, entry.path)
      } else {
        patch =
          patchByPath.get(entry.path) ??
          (await runGitStdout(cwd, [...args, '--', entry.path], {
            timeout: 20_000,
            maxBuffer: DIFF_MAX_BUFFER,
            allowNonZero: true
          }))
      }
    } catch {
      patch = ''
    }
    const code = layer === 'staged' ? entry.indexStatus : entry.workTreeStatus
    files.push({
      path: entry.path,
      status: gitStatusFromCode(code, entry.status),
      stage: layer,
      patch: patch.trimEnd()
    })
  }
  return files.sort((a, b) => a.path.localeCompare(b.path))
}

async function buildCombinedFiles(
  cwd: string,
  entries: ParsedPorcelainEntry[]
): Promise<GitWorkingChangeFile[]> {
  if (entries.length === 0) return []
  const trackedDiff = await runGitStdout(cwd, ['diff', 'HEAD', '--no-color'], {
    timeout: 30_000,
    maxBuffer: DIFF_MAX_BUFFER,
    allowNonZero: true
  })
  const patchByPath = splitUnifiedDiff(trackedDiff)
  const files: GitWorkingChangeFile[] = []
  for (const entry of entries) {
    let patch = ''
    try {
      patch =
        entry.status === 'untracked'
          ? await untrackedPatch(cwd, entry.path)
          : patchByPath.get(entry.path) ??
            (await runGitStdout(cwd, ['diff', 'HEAD', '--no-color', '--', entry.path], {
              timeout: 20_000,
              maxBuffer: DIFF_MAX_BUFFER,
              allowNonZero: true
            }))
    } catch {
      patch = ''
    }
    files.push({ ...entry, patch: patch.trimEnd() })
  }
  return files
    .map(({ path, status, stage, patch }) => ({ path, status, stage, patch }))
    .sort((a, b) => a.path.localeCompare(b.path))
}

async function resolveBranchBase(
  cwd: string,
  requestedBase?: string
): Promise<{ baseRef: string; baseCommit: string }> {
  const requested = requestedBase?.trim() ?? ''
  if (requested) {
    try {
      await runGit(cwd, ['check-ref-format', '--branch', requested])
      const baseCommit = (await runGit(cwd, ['merge-base', 'HEAD', requested])).stdout.trim()
      if (baseCommit) return { baseRef: requested, baseCommit }
    } catch {
      // A remembered branch may have been deleted; fall back automatically.
    }
  }

  let upstream = ''
  try {
    upstream = (
      await runGit(cwd, ['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}'])
    ).stdout.trim()
  } catch {
    // Local-only branches can still compare against a local/default base.
  }

  const currentBranch = await resolveCurrentBranch(cwd)
  const defaultBranch = await resolveRepositoryDefaultBranch(cwd)
  const recentAncestor = await resolveRecentAncestorBranch(
    cwd,
    currentBranch,
    defaultBranch
  )
  const candidates = [recentAncestor, defaultBranch, 'origin/main', 'origin/master', 'main', 'master']
  if (upstream) candidates.push(upstream)

  for (const baseRef of [...new Set(candidates.filter((ref): ref is string => Boolean(ref)))]) {
    try {
      const baseCommit = (await runGit(cwd, ['merge-base', 'HEAD', baseRef])).stdout.trim()
      if (baseCommit) return { baseRef, baseCommit }
    } catch {
      // Try the next conventional base.
    }
  }
  return { baseRef: 'HEAD', baseCommit: 'HEAD' }
}

function parseNameStatus(raw: string): Array<{ path: string; status: GitWorkingChangeStatus }> {
  const out: Array<{ path: string; status: GitWorkingChangeStatus }> = []
  for (const line of raw.split('\n')) {
    const parts = line.split('\t').filter(Boolean)
    const code = parts[0]?.[0] ?? ''
    const path = parts[parts.length - 1]?.trim() ?? ''
    if (!path) continue
    out.push({ path, status: gitStatusFromCode(code, 'modified') })
  }
  return out
}

async function buildBranchFiles(
  cwd: string,
  entries: ParsedPorcelainEntry[],
  baseCommit: string
): Promise<GitWorkingChangeFile[]> {
  const [patch, names] = await Promise.all([
    runGitStdout(cwd, ['diff', baseCommit, '--no-color'], {
      timeout: 30_000,
      maxBuffer: DIFF_MAX_BUFFER,
      allowNonZero: true
    }),
    runGitStdout(cwd, ['diff', '--name-status', '--find-renames', baseCommit, '--'], {
      timeout: 30_000,
      maxBuffer: DIFF_MAX_BUFFER,
      allowNonZero: true
    })
  ])
  const patchByPath = splitUnifiedDiff(patch)
  const files: GitWorkingChangeFile[] = []
  for (const entry of parseNameStatus(names)) {
    let filePatch = patchByPath.get(entry.path) ?? ''
    if (!filePatch) {
      filePatch = await runGitStdout(cwd, ['diff', baseCommit, '--no-color', '--', entry.path], {
        timeout: 20_000,
        maxBuffer: DIFF_MAX_BUFFER,
        allowNonZero: true
      })
    }
    files.push({ ...entry, stage: 'unstaged', patch: filePatch.trimEnd() })
  }
  const known = new Set(files.map((file) => file.path))
  for (const entry of entries) {
    if (entry.status !== 'untracked' || known.has(entry.path)) continue
    let filePatch = ''
    try {
      filePatch = await untrackedPatch(cwd, entry.path)
    } catch {
      // Keep the file visible even if a binary/no-index patch is unavailable.
    }
    files.push({
      path: entry.path,
      status: 'untracked',
      stage: 'unstaged',
      patch: filePatch.trimEnd()
    })
  }
  return files.sort((a, b) => a.path.localeCompare(b.path))
}

export async function getGitWorkingChanges(
  workspaceRoot: string,
  scope: GitChangeScope = 'working-tree',
  baseRef?: string
): Promise<GitWorkingChangesResult> {
  const cwd = workspaceRoot.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }

  try {
    const repositoryRoot = (await runGit(cwd, ['rev-parse', '--show-toplevel'])).stdout.trim()
    const porcelainLines = (await runGit(cwd, ['status', '--porcelain=v1'])).stdout
      .split('\n')
      .map((line) => line.trimEnd())
      .filter((line) => line.trim().length > 0)

    const entries = porcelainLines
      .map((line) => parsePorcelainEntry(line))
      .filter(
        (
          entry
        ): entry is ParsedPorcelainEntry => entry !== null
      )

    const branchBase = scope === 'branch' ? await resolveBranchBase(cwd, baseRef) : null

    const fingerprint = await workingChangesFingerprint(
      cwd,
      repositoryRoot,
      porcelainLines,
      entries.map((entry) => entry.path)
    )
    const scopedFingerprint = `${fingerprint}\u0002${branchBase?.baseRef ?? ''}\u0002${branchBase?.baseCommit ?? ''}`
    const cacheKey = `${cwd}\u0000${scope}`
    const cached = workingChangesCache.get(cacheKey)
    if (cached && cached.fingerprint === scopedFingerprint) {
      return cached.result
    }

    let result: GitWorkingChangesResult
    if (scope === 'branch' && branchBase) {
      result = {
        ok: true,
        repositoryRoot,
        scope,
        baseRef: branchBase.baseRef,
        files: await buildBranchFiles(cwd, entries, branchBase.baseCommit)
      }
    } else if (scope === 'staged') {
      result = { ok: true, repositoryRoot, scope, files: await buildLayerFiles(cwd, entries, 'staged') }
    } else if (scope === 'unstaged') {
      result = { ok: true, repositoryRoot, scope, files: await buildLayerFiles(cwd, entries, 'unstaged') }
    } else {
      const [files, stagedFiles, unstagedFiles] = await Promise.all([
        buildCombinedFiles(cwd, entries),
        buildLayerFiles(cwd, entries, 'staged'),
        buildLayerFiles(cwd, entries, 'unstaged')
      ])
      result = { ok: true, repositoryRoot, scope, files, stagedFiles, unstagedFiles }
    }
    if (workingChangesCache.size >= WORKING_CHANGES_CACHE_MAX_ROOTS && !workingChangesCache.has(cacheKey)) {
      const oldest = workingChangesCache.keys().next().value
      if (oldest !== undefined) workingChangesCache.delete(oldest)
    }
    workingChangesCache.set(cacheKey, { fingerprint: scopedFingerprint, result })
    return result
  } catch (error) {
    return gitWorkingChangesFailure(error)
  }
}

export async function createAndSwitchGitBranch(
  workspaceRoot: string,
  branchName: string
): Promise<GitBranchesResult> {
  const cwd = workspaceRoot.trim()
  const branch = branchName.trim()
  if (!cwd) return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  if (!branch) return { ok: false, reason: 'error', message: 'Branch name is required.' }
  try {
    await runGit(cwd, ['check-ref-format', '--branch', branch])
    const runtimeCheckoutFailure = await protectRuntimeCheckout(cwd)
    if (runtimeCheckoutFailure) return runtimeCheckoutFailure
    try {
      await runGit(cwd, ['switch', '-c', branch], 20_000)
    } catch {
      await runGit(cwd, ['checkout', '-b', branch], 20_000)
    }
    return getGitBranches(cwd)
  } catch (error) {
    return gitFailure(error)
  }
}

const GIT_PATH_BATCH_SIZE = 50

function isSafeGitPath(path: string): boolean {
  const normalized = path.replace(/\\/g, '/').trim()
  if (!normalized || normalized.startsWith('/') || normalized.includes('\0')) return false
  return !normalized.split('/').some((part) => part === '..')
}

function gitCommitFailure(error: unknown): GitCommitResult {
  const message = error instanceof Error ? error.message : String(error)
  if (/not a git repository/i.test(message)) {
    return { ok: false, reason: 'not_git_repo', message: 'The working directory is not a Git repository.' }
  }
  if (/ENOENT/i.test(message) || /spawn git/i.test(message)) {
    return { ok: false, reason: 'git_unavailable', message: 'Git executable was not found.' }
  }
  return { ok: false, reason: 'error', message }
}

async function hasStagedChanges(cwd: string): Promise<boolean> {
  try {
    await runGit(cwd, ['diff', '--cached', '--quiet'], 10_000)
    return false
  } catch {
    return true
  }
}

async function stageGitPaths(cwd: string, paths: string[]): Promise<void> {
  for (let index = 0; index < paths.length; index += GIT_PATH_BATCH_SIZE) {
    const batch = paths.slice(index, index + GIT_PATH_BATCH_SIZE)
    await runGit(cwd, ['add', '--', ...batch], 60_000)
  }
}

function gitPathActionFailure(error: unknown): GitPathActionResult {
  const message = error instanceof Error ? error.message : String(error)
  if (/not a git repository/i.test(message)) {
    return { ok: false, reason: 'not_git_repo', message: 'The working directory is not a Git repository.' }
  }
  if (/ENOENT/i.test(message) || /spawn git/i.test(message)) {
    return { ok: false, reason: 'git_unavailable', message: 'Git executable was not found.' }
  }
  return { ok: false, reason: 'error', message }
}

function safeUniqueGitPaths(paths: string[]): string[] {
  return [...new Set(paths.map((path) => path.trim()).filter(isSafeGitPath))]
}

export async function stageGitChanges(
  workspaceRoot: string,
  paths: string[]
): Promise<GitPathActionResult> {
  const cwd = workspaceRoot.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }
  const safePaths = safeUniqueGitPaths(paths)
  if (safePaths.length === 0) {
    return { ok: false, reason: 'invalid_paths', message: 'Select at least one safe file path.' }
  }
  try {
    const repositoryRoot = (await runGit(cwd, ['rev-parse', '--show-toplevel'])).stdout.trim()
    await stageGitPaths(cwd, safePaths)
    invalidateWorkingChangesCache(cwd)
    return { ok: true, repositoryRoot, fileCount: safePaths.length }
  } catch (error) {
    return gitPathActionFailure(error)
  }
}

export async function unstageGitChanges(
  workspaceRoot: string,
  paths: string[]
): Promise<GitPathActionResult> {
  const cwd = workspaceRoot.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }
  const safePaths = safeUniqueGitPaths(paths)
  if (safePaths.length === 0) {
    return { ok: false, reason: 'invalid_paths', message: 'Select at least one safe file path.' }
  }
  try {
    const repositoryRoot = (await runGit(cwd, ['rev-parse', '--show-toplevel'])).stdout.trim()
    let hasHead = true
    try {
      await runGit(cwd, ['rev-parse', '--verify', 'HEAD'])
    } catch {
      hasHead = false
    }
    if (hasHead) {
      try {
        await runGit(cwd, ['restore', '--staged', '--', ...safePaths], 60_000)
      } catch {
        await runGit(cwd, ['reset', 'HEAD', '--', ...safePaths], 60_000)
      }
    } else {
      await runGit(cwd, ['rm', '--cached', '--ignore-unmatch', '--', ...safePaths], 60_000)
    }
    invalidateWorkingChangesCache(cwd)
    return { ok: true, repositoryRoot, fileCount: safePaths.length }
  } catch (error) {
    return gitPathActionFailure(error)
  }
}

function gitPushFailure(error: unknown): GitPushResult {
  const message = error instanceof Error ? error.message : String(error)
  if (/not a git repository/i.test(message)) {
    return { ok: false, reason: 'not_git_repo', message: 'The working directory is not a Git repository.' }
  }
  if (/ENOENT/i.test(message) || /spawn git/i.test(message)) {
    return { ok: false, reason: 'git_unavailable', message: 'Git executable was not found.' }
  }
  if (/non-fast-forward|fetch first|rejected/i.test(message)) {
    return {
      ok: false,
      reason: 'rejected',
      message: 'The remote branch has newer commits. Update your branch before pushing.'
    }
  }
  return { ok: false, reason: 'error', message }
}

function gitPullFailure(error: unknown): GitPullResult {
  const message = error instanceof Error ? error.message : String(error)
  if (/not a git repository/i.test(message)) {
    return { ok: false, reason: 'not_git_repo', message: 'The working directory is not a Git repository.' }
  }
  if (/ENOENT/i.test(message) || /spawn git/i.test(message)) {
    return { ok: false, reason: 'git_unavailable', message: 'Git executable was not found.' }
  }
  if (/not possible to fast-forward|divergent branches|non-fast-forward/i.test(message)) {
    return {
      ok: false,
      reason: 'diverged',
      message: 'Local and remote commits have diverged. Choose merge or rebase before pulling.'
    }
  }
  if (/local changes.*overwritten|would be overwritten|unstaged changes/i.test(message)) {
    return {
      ok: false,
      reason: 'dirty_worktree',
      message: 'Commit or stash local changes before pulling.'
    }
  }
  return { ok: false, reason: 'error', message }
}

export async function pullGitBranch(workspaceRoot: string): Promise<GitPullResult> {
  const cwd = workspaceRoot.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }
  try {
    const repositoryRoot = (await runGit(cwd, ['rev-parse', '--show-toplevel'])).stdout.trim()
    const branch = (await runGit(cwd, ['branch', '--show-current'])).stdout.trim()
    if (!branch) {
      return { ok: false, reason: 'detached_head', message: 'Switch to a branch before pulling.' }
    }
    let upstream = ''
    try {
      upstream = (
        await runGit(cwd, ['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}'])
      ).stdout.trim()
    } catch {
      return { ok: false, reason: 'no_upstream', message: 'Publish this branch before pulling.' }
    }
    const before = (await runGit(cwd, ['rev-parse', 'HEAD'])).stdout.trim()
    // Never introduce an implicit merge commit from a toolbar action.
    await runGit(cwd, ['pull', '--ff-only'], 120_000, DIFF_MAX_BUFFER)
    const after = (await runGit(cwd, ['rev-parse', 'HEAD'])).stdout.trim()
    invalidateWorkingChangesCache(cwd)
    return { ok: true, repositoryRoot, branch, upstream, updated: before !== after }
  } catch (error) {
    return gitPullFailure(error)
  }
}

export async function pushGitBranch(workspaceRoot: string): Promise<GitPushResult> {
  const cwd = workspaceRoot.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }
  try {
    const repositoryRoot = (await runGit(cwd, ['rev-parse', '--show-toplevel'])).stdout.trim()
    const branch = (await runGit(cwd, ['branch', '--show-current'])).stdout.trim()
    if (!branch) {
      return { ok: false, reason: 'detached_head', message: 'Create or switch to a branch before pushing.' }
    }

    const remotes = (await runGit(cwd, ['remote'])).stdout
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
    if (remotes.length === 0) {
      return { ok: false, reason: 'no_remote', message: 'No Git remote is configured.' }
    }

    let upstream = ''
    try {
      upstream = (
        await runGit(cwd, ['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{upstream}'])
      ).stdout.trim()
    } catch {
      upstream = ''
    }

    if (upstream) {
      const counts = (await runGit(cwd, ['rev-list', '--left-right', '--count', `HEAD...${upstream}`]))
        .stdout.trim()
        .split(/\s+/)
      const ahead = Number.parseInt(counts[0] ?? '0', 10) || 0
      const behind = Number.parseInt(counts[1] ?? '0', 10) || 0
      if (behind > 0) {
        return {
          ok: false,
          reason: 'behind_remote',
          message: 'The remote branch has newer commits. Update your branch before pushing.'
        }
      }
      if (ahead > 0) await runGit(cwd, ['push'], 120_000, DIFF_MAX_BUFFER)
      const commitHash = (await runGit(cwd, ['rev-parse', '--short', 'HEAD'])).stdout.trim()
      return { ok: true, repositoryRoot, branch, upstream, commitHash, pushed: ahead > 0 }
    }

    const remote = remotes.includes('origin') ? 'origin' : remotes[0]!
    await runGit(cwd, ['push', '--set-upstream', remote, branch], 120_000, DIFF_MAX_BUFFER)
    const commitHash = (await runGit(cwd, ['rev-parse', '--short', 'HEAD'])).stdout.trim()
    return {
      ok: true,
      repositoryRoot,
      branch,
      upstream: `${remote}/${branch}`,
      commitHash,
      pushed: true
    }
  } catch (error) {
    return gitPushFailure(error)
  }
}

export async function commitGitChanges(
  workspaceRoot: string,
  message: string,
  paths?: string[]
): Promise<GitCommitResult> {
  const cwd = workspaceRoot.trim()
  const commitMessage = message.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }
  if (!commitMessage) {
    return { ok: false, reason: 'invalid_message', message: 'Commit message is required.' }
  }

  try {
    const repositoryRoot = (await runGit(cwd, ['rev-parse', '--show-toplevel'])).stdout.trim()
    const targetPaths = paths?.map((path) => path.trim()).filter(Boolean)
    let committedPaths: string[]

    if (targetPaths === undefined) {
      // Standard Git flow: the index is the commit selection. Do not silently
      // stage working-directory changes from a Commit button.
      committedPaths = (await runGit(cwd, ['diff', '--cached', '--name-only'])).stdout
        .split('\n')
        .map((path) => path.trim())
        .filter(Boolean)
      if (committedPaths.length === 0 || !(await hasStagedChanges(cwd))) {
        return { ok: false, reason: 'nothing_to_commit', message: 'No changes staged for commit.' }
      }
      await runGit(cwd, ['commit', '-m', commitMessage], 60_000)
    } else {
      // Explicit paths remain available for older/advanced callers.
      const safePaths = [...new Set(targetPaths.filter(isSafeGitPath))]
      if (safePaths.length === 0) {
        return { ok: false, reason: 'nothing_to_commit', message: 'No changes to commit.' }
      }
      await stageGitPaths(cwd, safePaths)
      if (!(await hasStagedChanges(cwd))) {
        return { ok: false, reason: 'nothing_to_commit', message: 'No changes staged for commit.' }
      }
      // `--only` keeps previously staged but unselected files out of this commit.
      await runGit(cwd, ['commit', '--only', '-m', commitMessage, '--', ...safePaths], 60_000)
      committedPaths = safePaths
    }
    const commitHash = (await runGit(cwd, ['rev-parse', '--short', 'HEAD'])).stdout.trim()
    const summary = (await runGit(cwd, ['show', '-s', '--format=%s', 'HEAD'])).stdout.trim()
    invalidateWorkingChangesCache(cwd)

    return {
      ok: true,
      repositoryRoot,
      commitHash,
      summary,
      fileCount: committedPaths.length
    }
  } catch (error) {
    return gitCommitFailure(error)
  }
}

function gitPathBasename(path: string): string {
  const parts = path.replace(/\\/g, '/').split('/')
  return parts[parts.length - 1] || path
}

function gitMessageSuggestionFailure(error: unknown): GitCommitMessageSuggestionResult {
  const message = error instanceof Error ? error.message : String(error)
  if (/not a git repository/i.test(message)) {
    return { ok: false, reason: 'not_git_repo', message: 'The working directory is not a Git repository.' }
  }
  if (/ENOENT/i.test(message) || /spawn git/i.test(message)) {
    return { ok: false, reason: 'git_unavailable', message: 'Git executable was not found.' }
  }
  return { ok: false, reason: 'error', message }
}

export async function suggestGitCommitMessage(
  workspaceRoot: string,
  paths?: string[]
): Promise<GitCommitMessageSuggestionResult> {
  const cwd = workspaceRoot.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }

  try {
    const changes = await getGitWorkingChanges(cwd)
    if (!changes.ok) {
      return { ok: false, reason: changes.reason, message: changes.message }
    }

    let targetFiles = changes.files
    if (paths && paths.length > 0) {
      const allowed = new Set(paths)
      targetFiles = targetFiles.filter((file) => allowed.has(file.path))
    }
    if (targetFiles.length === 0) {
      return { ok: false, reason: 'nothing_to_commit', message: 'No changes to suggest for.' }
    }

    if (targetFiles.length === 1) {
      const file = targetFiles[0]!
      const name = gitPathBasename(file.path)
      const message =
        file.status === 'added' || file.status === 'untracked' || file.status === 'copied'
          ? `Add ${name}`
          : file.status === 'deleted'
            ? `Remove ${name}`
            : `Update ${name}`
      return { ok: true, message }
    }

    let added = 0
    let deleted = 0
    let modified = 0
    for (const file of targetFiles) {
      if (file.status === 'added' || file.status === 'untracked' || file.status === 'copied') {
        added += 1
      } else if (file.status === 'deleted') {
        deleted += 1
      } else {
        modified += 1
      }
    }

    const summaryParts: string[] = []
    if (added > 0) summaryParts.push(`add ${added} file(s)`)
    if (modified > 0) summaryParts.push(`update ${modified} file(s)`)
    if (deleted > 0) summaryParts.push(`remove ${deleted} file(s)`)

    const headline =
      summaryParts.length === 1
        ? summaryParts[0]!.charAt(0).toUpperCase() + summaryParts[0]!.slice(1)
        : `Update ${targetFiles.length} files`

    const listing = targetFiles
      .slice(0, 5)
      .map((file) => `- ${file.path}`)
      .join('\n')
    const remainder =
      targetFiles.length > 5 ? `\n- …and ${targetFiles.length - 5} more` : ''

    return { ok: true, message: `${headline}\n\n${listing}${remainder}` }
  } catch (error) {
    return gitMessageSuggestionFailure(error)
  }
}

const GIT_LOG_LIMIT = 200

function gitLogFailure(error: unknown): GitLogResult {
  const message = error instanceof Error ? error.message : String(error)
  if (/not a git repository/i.test(message)) {
    return { ok: false, reason: 'not_git_repo', message: 'The working directory is not a Git repository.' }
  }
  if (/ENOENT/i.test(message) || /spawn git/i.test(message)) {
    return { ok: false, reason: 'git_unavailable', message: 'Git executable was not found.' }
  }
  return { ok: false, reason: 'error', message }
}

async function tryGitStdout(cwd: string, args: string[]): Promise<string | null> {
  try {
    return (await runGit(cwd, args)).stdout.trim()
  } catch {
    return null
  }
}

function parseGitLogLine(line: string): GitLogCommit | null {
  const parts = line.split('\0')
  if (parts.length < 5) return null
  const [hash, parentsRaw, subject, author, atRaw] = parts
  if (!hash || !subject || !author || !atRaw) return null
  const authoredAtMs = Number(atRaw) * 1000
  if (!Number.isFinite(authoredAtMs)) return null
  return {
    hash,
    shortHash: hash.slice(0, 7),
    parents: parentsRaw.split(' ').filter(Boolean),
    subject,
    author,
    authoredAt: new Date(authoredAtMs).toISOString()
  }
}

async function readGitUpstream(cwd: string): Promise<GitLogUpstream | null> {
  const upstreamRef = await tryGitStdout(cwd, ['rev-parse', '--abbrev-ref', '@{upstream}'])
  if (!upstreamRef || upstreamRef === '@{upstream}') return null

  const upstreamHash = await tryGitStdout(cwd, ['rev-parse', '@{upstream}'])
  if (!upstreamHash) return null

  const countRaw = await runGitStdout(cwd, ['rev-list', '--left-right', '--count', 'HEAD...@{upstream}'], {
    allowNonZero: true
  })
  const [aheadRaw, behindRaw] = countRaw.trim().split(/\s+/)
  const ahead = Number(aheadRaw)
  const behind = Number(behindRaw)

  return {
    ref: upstreamRef,
    hash: upstreamHash,
    ahead: Number.isFinite(ahead) ? ahead : 0,
    behind: Number.isFinite(behind) ? behind : 0
  }
}

function gitHubRepositoryFailure(error: unknown): GitHubRepositoryResult {
  const message = error instanceof Error ? error.message : String(error)
  if (/not a git repository/i.test(message)) {
    return {
      ok: false,
      reason: 'not_git_repo',
      message: 'The working directory is not a Git repository.'
    }
  }
  if (/ENOENT/i.test(message) || /spawn git/i.test(message)) {
    return { ok: false, reason: 'git_unavailable', message: 'Git executable was not found.' }
  }
  return { ok: false, reason: 'error', message }
}

function uniqueRemoteNames(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>()
  const names: string[] = []
  for (const value of values) {
    const name = value?.trim() ?? ''
    if (!name || seen.has(name)) continue
    seen.add(name)
    names.push(name)
  }
  return names
}

export async function getGitHubRepository(workspaceRoot: string): Promise<GitHubRepositoryResult> {
  const cwd = workspaceRoot.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }

  try {
    await runGit(cwd, ['rev-parse', '--show-toplevel'])
    const remoteNames = (await tryGitStdout(cwd, ['remote']))
      ?.split('\n')
      .map((line) => line.trim())
      .filter(Boolean) ?? []
    if (remoteNames.length === 0) {
      return { ok: false, reason: 'no_github_remote', message: 'No git remotes configured.' }
    }

    const currentBranch = await tryGitStdout(cwd, ['branch', '--show-current'])
    const trackingRemote = currentBranch
      ? await tryGitStdout(cwd, ['config', '--get', `branch.${currentBranch}.remote`])
      : null
    const candidates = uniqueRemoteNames([
      trackingRemote,
      remoteNames.includes('origin') ? 'origin' : null,
      ...remoteNames
    ])

    for (const remoteName of candidates) {
      const remoteUrl = await tryGitStdout(cwd, ['remote', 'get-url', remoteName])
      const parsed = parseGitRemoteRepository(remoteUrl)
      if (!parsed) continue
      return { ok: true, ...parsed }
    }

    return { ok: false, reason: 'no_github_remote', message: 'No browsable git remote found.' }
  } catch (error) {
    return gitHubRepositoryFailure(error)
  }
}

export async function getGitLog(
  workspaceRoot: string,
  refreshRemote = false
): Promise<GitLogResult> {
  const cwd = workspaceRoot.trim()
  if (!cwd) {
    return { ok: false, reason: 'no_workspace', message: 'No working directory selected.' }
  }

  try {
    const repositoryRoot = (await runGit(cwd, ['rev-parse', '--show-toplevel'])).stdout.trim()
    const remote = await readGitRemoteState(cwd, refreshRemote)
    const currentBranch = (await runGit(cwd, ['branch', '--show-current'])).stdout.trim() || null
    const headHash = (await runGit(cwd, ['rev-parse', 'HEAD'])).stdout.trim()
    const upstream = await readGitUpstream(cwd)
    const logRef = currentBranch ?? 'HEAD'
    const raw = await runGitStdout(cwd, [
      'log',
      `--topo-order`,
      `-n${GIT_LOG_LIMIT}`,
      '--format=%H%x00%P%x00%s%x00%an%x00%at',
      logRef,
      ...(upstream ? [upstream.ref] : [])
    ])
    const commits = raw
      .split('\n')
      .map((line) => parseGitLogLine(line.trim()))
      .filter((entry): entry is GitLogCommit => entry !== null)

    return {
      ok: true,
      repositoryRoot,
      branch: currentBranch,
      headHash,
      upstream,
      hasRemote: remote.hasRemote,
      remoteRefreshError: remote.refreshError,
      remoteRefreshedAt: remote.refreshedAt,
      commits
    }
  } catch (error) {
    return gitLogFailure(error)
  }
}
