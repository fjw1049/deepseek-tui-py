/**
 * Classify whether a shell command is a read-only "probe" that may fold into
 * the same tool batch as read_file / grep / list_dir.
 *
 * Conservative allowlist: unknown binaries, write redirects, heredocs, and
 * mutating git/npm/pip subcommands stay solo heavy cards.
 */

const PROBE_BINARIES = new Set([
  'ls',
  'll',
  'dir',
  'tree',
  'find',
  'locate',
  'pwd',
  'which',
  'type',
  'whereis',
  'whoami',
  'id',
  'hostname',
  'uname',
  'date',
  'cal',
  'cat',
  'head',
  'tail',
  'wc',
  'file',
  'stat',
  'du',
  'df',
  'free',
  'env',
  'printenv',
  'echo',
  'printf',
  'true',
  'false',
  'test',
  '[',
  'rg',
  'grep',
  'egrep',
  'fgrep',
  'ag',
  'ack',
  'fd',
  'fdfind',
  'jq',
  'yq',
  'basename',
  'dirname',
  'realpath',
  'readlink',
  'ps',
  'pgrep',
  'lsof',
  'git',
  'gh',
  'npm',
  'pnpm',
  'yarn',
  'pip',
  'pip3',
  'python',
  'python3',
  'node',
  'rustc',
  'go',
  'cargo',
  'docker',
  'kubectl'
])

const GIT_PROBE_SUBCOMMANDS = new Set([
  'status',
  'log',
  'show',
  'diff',
  'branch',
  'remote',
  'tag',
  'blame',
  'shortlog',
  'describe',
  'rev-parse',
  'ls-files',
  'ls-tree',
  'cat-file',
  'whatchanged',
  'stash',
  'config'
])

const PACKAGE_PROBE_SUBCOMMANDS = new Set([
  'ls',
  'list',
  'll',
  'view',
  'info',
  'show',
  'outdated',
  'why',
  'explain',
  'version',
  '--version',
  '-v',
  '-V'
])

const DOCKER_PROBE_SUBCOMMANDS = new Set([
  'ps',
  'images',
  'image',
  'inspect',
  'logs',
  'version',
  'info',
  'compose'
])

const GH_PROBE_SUBCOMMANDS = new Set([
  'status',
  'repo',
  'pr',
  'issue',
  'run',
  'release',
  'api',
  'browse'
])

const GH_MUTATING_ACTIONS = new Set([
  'create',
  'close',
  'edit',
  'delete',
  'merge',
  'ready',
  'review',
  'comment',
  'lock',
  'unlock',
  'reopen',
  'transfer',
  'develop',
  'pin',
  'unpin'
])

/** Quote-aware split on `&&` / `||` / `;` / `|` / newlines. */
export function splitCompoundCommands(command: string): string[] {
  const parts: string[] = []
  let cur = ''
  let quote: '"' | "'" | null = null
  for (let i = 0; i < command.length; i += 1) {
    const ch = command[i]!
    const next = command[i + 1]
    if (quote) {
      cur += ch
      if (ch === quote) quote = null
      continue
    }
    if (ch === '"' || ch === "'") {
      quote = ch
      cur += ch
      continue
    }
    if ((ch === '&' && next === '&') || (ch === '|' && next === '|')) {
      if (cur.trim()) parts.push(cur.trim())
      cur = ''
      i += 1
      continue
    }
    if (ch === '|' || ch === ';' || ch === '\n') {
      if (cur.trim()) parts.push(cur.trim())
      cur = ''
      continue
    }
    cur += ch
  }
  if (cur.trim()) parts.push(cur.trim())
  return parts
}

function roughTokens(segment: string): string[] {
  const tokens: string[] = []
  let cur = ''
  let quote: '"' | "'" | null = null
  for (let i = 0; i < segment.length; i += 1) {
    const ch = segment[i]!
    if (quote) {
      cur += ch
      if (ch === quote) {
        quote = null
        tokens.push(cur)
        cur = ''
      }
      continue
    }
    if (ch === '"' || ch === "'") {
      quote = ch
      cur = ch
      continue
    }
    if (/\s/.test(ch)) {
      if (cur) {
        tokens.push(cur)
        cur = ''
      }
      continue
    }
    cur += ch
  }
  if (cur) tokens.push(cur)
  return tokens
}

function stripLeadingEnvAssignments(tokens: string[]): string[] {
  let i = 0
  while (i < tokens.length && /^[A-Za-z_][A-Za-z0-9_]*=/.test(tokens[i]!)) i += 1
  return tokens.slice(i)
}

function baseBinary(token: string): string {
  const bare = token.replace(/^['"]|['"]$/g, '')
  const slash = bare.lastIndexOf('/')
  return (slash >= 0 ? bare.slice(slash + 1) : bare).toLowerCase()
}

function firstNonFlag(args: string[]): string | undefined {
  for (const arg of args) {
    if (!arg.startsWith('-')) return arg.replace(/^['"]|['"]$/g, '')
  }
  return undefined
}

/** True when the command writes to a real destination (not /dev/null). */
export function hasUnsafeShellRedirect(command: string): boolean {
  if (/<<\s*[-]?['"]?\w+/.test(command)) return true
  // Match `>` / `>>` / `n>` (n = optional fd number) that target a real file:
  // not `/dev/null` and not an fd dup (`>&1`, `2>&1`). The optional `\d*`
  // before `>` lets `2> err.txt` be caught while `2>&1` / `2>/dev/null` pass.
  const re = /\d*>{1,2}\s*(?!\/dev\/null\b)(?!&)/
  return re.test(command)
}

/**
 * Command substitution (`$(...)`, backticks) and process substitution
 * (`<(...)`, `>(...)`) can smuggle an arbitrary command past first-token
 * inspection (`echo $(rm -rf x)`), so any command using them is never a probe.
 */
function hasCommandSubstitution(command: string): boolean {
  return /\$\(|`|<\(|>\(/.test(command)
}

const FIND_MUTATING_ACTIONS = new Set([
  '-delete',
  '-exec',
  '-execdir',
  '-ok',
  '-okdir',
  '-fprint',
  '-fprint0',
  '-fprintf',
  '-fls',
  '-fput'
])

function isProbeFind(args: string[]): boolean {
  return !args.some((a) => FIND_MUTATING_ACTIONS.has(a.replace(/^['"]|['"]$/g, '')))
}

function isProbeGit(args: string[]): boolean {
  const sub = firstNonFlag(args)?.toLowerCase()
  if (!sub || !GIT_PROBE_SUBCOMMANDS.has(sub)) return false
  if (sub === 'stash') {
    const action = firstNonFlag(args.slice(args.findIndex((a) => !a.startsWith('-')) + 1))
    return !action || action === 'list' || action === 'show'
  }
  if (sub === 'config') {
    return args.some((a) => a === '--get' || a === '--list' || a === '-l' || a.startsWith('--get='))
  }
  return true
}

function isProbePackageManager(args: string[]): boolean {
  if (args.some((a) => a === '--version' || a === '-v' || a === '-V')) return true
  const sub = firstNonFlag(args)?.toLowerCase()
  return Boolean(sub && PACKAGE_PROBE_SUBCOMMANDS.has(sub))
}

function isProbePython(args: string[]): boolean {
  return args.some((a) => a === '--version' || a === '-V')
}

function isProbeNode(args: string[]): boolean {
  return args.some((a) => a === '--version' || a === '-v' || a === '-V')
}

function isProbeCargo(args: string[]): boolean {
  if (args.some((a) => a === '--version' || a === '-V')) return true
  const sub = firstNonFlag(args)?.toLowerCase()
  return sub === 'tree' || sub === 'metadata' || sub === 'version'
}

function isProbeGo(args: string[]): boolean {
  if (args.some((a) => a === 'version')) return true
  const sub = firstNonFlag(args)?.toLowerCase()
  return sub === 'version' || sub === 'env' || sub === 'list'
}

function isProbeDocker(args: string[]): boolean {
  const sub = firstNonFlag(args)?.toLowerCase()
  if (!sub || !DOCKER_PROBE_SUBCOMMANDS.has(sub)) return false
  if (sub === 'compose') {
    const action = firstNonFlag(args.slice(args.findIndex((a) => !a.startsWith('-')) + 1))
    return action === 'ps' || action === 'ls' || action === 'images' || action === 'config'
  }
  if (sub === 'image') {
    const action = firstNonFlag(args.slice(args.findIndex((a) => !a.startsWith('-')) + 1))
    return action === 'ls' || action === 'inspect' || action === 'history'
  }
  return true
}

function isProbeGh(args: string[]): boolean {
  const sub = firstNonFlag(args)?.toLowerCase()
  if (!sub || !GH_PROBE_SUBCOMMANDS.has(sub)) return false
  const action = firstNonFlag(args.slice(args.findIndex((a) => !a.startsWith('-')) + 1))
  if (!action) return true
  if (GH_MUTATING_ACTIONS.has(action.toLowerCase())) return false
  return true
}

function isProbeSegment(segment: string): boolean {
  const tokens = stripLeadingEnvAssignments(roughTokens(segment))
  if (tokens.length === 0) return false
  const bin = baseBinary(tokens[0]!)
  if (!PROBE_BINARIES.has(bin)) return false
  const args = tokens.slice(1)
  if (bin === 'find') return isProbeFind(args)
  if (bin === 'git') return isProbeGit(args)
  if (bin === 'npm' || bin === 'pnpm' || bin === 'yarn' || bin === 'pip' || bin === 'pip3') {
    return isProbePackageManager(args)
  }
  if (bin === 'python' || bin === 'python3') return isProbePython(args)
  if (bin === 'node' || bin === 'rustc') return isProbeNode(args)
  if (bin === 'cargo') return isProbeCargo(args)
  if (bin === 'go') return isProbeGo(args)
  if (bin === 'docker') return isProbeDocker(args)
  if (bin === 'kubectl') {
    const sub = firstNonFlag(args)?.toLowerCase()
    return (
      sub === 'get' ||
      sub === 'describe' ||
      sub === 'logs' ||
      sub === 'top' ||
      sub === 'version' ||
      sub === 'api-resources' ||
      sub === 'explain'
    )
  }
  if (bin === 'gh') return isProbeGh(args)
  return true
}

/** True when every segment of the command is a read-only probe. */
export function isProbeShellCommand(command: string | undefined | null): boolean {
  const text = command?.trim()
  if (!text) return false
  if (hasCommandSubstitution(text)) return false
  if (hasUnsafeShellRedirect(text)) return false
  const segments = splitCompoundCommands(text)
  if (segments.length === 0) return false
  return segments.every(isProbeSegment)
}
