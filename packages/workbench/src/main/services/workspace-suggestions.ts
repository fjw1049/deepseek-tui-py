import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

const execFileAsync = promisify(execFile)

export type WorkspaceSuggestion = {
  id: string
  title: string
  desc: string
  prompt: string
  tone: 'blue' | 'emerald' | 'violet' | 'orange'
}

export type WorkspaceSuggestionsResult =
  | { ok: true; suggestions: WorkspaceSuggestion[] }
  | { ok: false; suggestions: null }

const TONES: WorkspaceSuggestion['tone'][] = ['blue', 'emerald', 'violet', 'orange']

async function git(cwd: string, args: string[]): Promise<string> {
  try {
    const { stdout } = await execFileAsync('git', args, { cwd, timeout: 5000, maxBuffer: 512 * 1024 })
    return String(stdout).trim()
  } catch {
    return ''
  }
}

async function readProjectName(cwd: string): Promise<string | null> {
  for (const file of ['package.json', 'pyproject.toml', 'Cargo.toml']) {
    try {
      const content = await readFile(join(cwd, file), 'utf-8')
      if (file === 'package.json') {
        const pkg = JSON.parse(content)
        if (pkg.name) return pkg.name
      } else {
        const match = content.match(/^name\s*=\s*["']([^"']+)["']/m)
        if (match) return match[1]
      }
    } catch {
      /* skip */
    }
  }
  return null
}

function shortenTopic(raw: string): string {
  const topic = raw.replace(/[-_]/g, ' ')
  if (topic.length <= 20) return topic
  return topic.slice(0, 18) + '…'
}

function parseBranchIntent(branch: string): WorkspaceSuggestion | null {
  const fixMatch = branch.match(/^fix[/_-](.+)/)
  if (fixMatch) {
    return {
      id: 'branch-fix',
      title: `修复 ${shortenTopic(fixMatch[1])}`,
      desc: '当前分支正在修一个问题，继续推进',
      prompt: `当前分支是 ${branch}，帮我分析已有改动、定位问题并完成修复。`,
      tone: 'emerald'
    }
  }
  const featMatch = branch.match(/^feat(?:ure)?[/_-](.+)/)
  if (featMatch) {
    return {
      id: 'branch-feat',
      title: `实现 ${shortenTopic(featMatch[1])}`,
      desc: '当前分支在开发新功能，继续推进',
      prompt: `当前分支是 ${branch}，帮我继续实现这个功能，检查还有什么遗漏。`,
      tone: 'violet'
    }
  }
  const refactorMatch = branch.match(/^refactor[/_-](.+)/)
  if (refactorMatch) {
    return {
      id: 'branch-refactor',
      title: `重构 ${shortenTopic(refactorMatch[1])}`,
      desc: '当前分支在做重构，继续推进',
      prompt: `当前分支是 ${branch}，帮我继续这次重构，确保功能不回归。`,
      tone: 'orange'
    }
  }
  return null
}

function shortenCommitSubject(subject: string): string {
  // Truncate to ~20 chars for display, keep it readable
  const cleaned = subject.trim()
  if (cleaned.length <= 24) return cleaned
  return cleaned.slice(0, 22) + '…'
}

function parseCommitSuggestions(log: string): WorkspaceSuggestion[] {
  const results: WorkspaceSuggestion[] = []
  const lines = log.split('\n').filter(Boolean).slice(0, 5)
  for (const line of lines) {
    const featMatch = line.match(/^(?:[a-f0-9]+ )?feat(?:\((.+?)\))?:\s*(.+)/i)
    if (featMatch) {
      const scope = featMatch[1]
      const subject = featMatch[2]
      const label = scope ? `${scope} 功能` : shortenCommitSubject(subject)
      results.push({
        id: `commit-feat-${results.length}`,
        title: `继续完善 ${label}`,
        desc: '最近加的新功能，检查是否完整并补充测试',
        prompt: `最近提交了新功能 "${subject}"，帮我检查是否完整，补充测试或文档。`,
        tone: 'violet'
      })
    }
    const fixMatch = line.match(/^(?:[a-f0-9]+ )?fix(?:\((.+?)\))?:\s*(.+)/i)
    if (fixMatch) {
      const scope = fixMatch[1]
      const subject = fixMatch[2]
      const label = scope ? `${scope} 修复` : shortenCommitSubject(subject)
      results.push({
        id: `commit-fix-${results.length}`,
        title: `验证 ${label}`,
        desc: '最近的修复，确认没有遗漏和回归',
        prompt: `最近修复了 "${subject}"，帮我验证是否完整，有没有引入新问题。`,
        tone: 'emerald'
      })
    }
    if (results.length >= 2) break
  }
  return results
}

export async function getWorkspaceSuggestions(cwd: string): Promise<WorkspaceSuggestionsResult> {
  if (!cwd) return { ok: false, suggestions: null }

  const signals: WorkspaceSuggestion[] = []

  // 1. Uncommitted changes
  const diffStat = await git(cwd, ['diff', '--stat', 'HEAD'])
  if (diffStat) {
    const files = diffStat.split('\n').slice(0, -1).map(l => l.split('|')[0].trim()).filter(Boolean)
    const fileCount = files.length
    signals.push({
      id: 'uncommitted',
      title: '继续未完成的改动',
      desc: `有 ${fileCount} 个文件尚未提交，可以帮你 review 或补完`,
      prompt: '我有未完成的改动，帮我 review 这些改动并补完剩余工作。',
      tone: 'blue'
    })
  }

  // 2. Staged but uncommitted
  const stagedStat = await git(cwd, ['diff', '--cached', '--stat'])
  if (stagedStat && !diffStat) {
    signals.push({
      id: 'staged',
      title: '提交暂存的改动',
      desc: '有已暂存但未提交的改动',
      prompt: '我有已暂存的改动，帮我 review 并生成一个合适的 commit message。',
      tone: 'blue'
    })
  }

  // 3. Branch name
  const branch = await git(cwd, ['branch', '--show-current'])
  if (branch && branch !== 'main' && branch !== 'master') {
    const branchSuggestion = parseBranchIntent(branch)
    if (branchSuggestion) signals.push(branchSuggestion)
  }

  // 4. Recent commits
  const log = await git(cwd, ['log', '--oneline', '-5'])
  if (log) {
    signals.push(...parseCommitSuggestions(log))
  }

  // 5. TODO/FIXME
  try {
    const { stdout } = await execFileAsync(
      'grep',
      ['-r', '-l', '--include=*.py', '--include=*.ts', '--include=*.tsx', '--include=*.js', '-E', 'TODO|FIXME', '.'],
      { cwd, timeout: 3000, maxBuffer: 256 * 1024 }
    )
    const todoFiles = String(stdout).trim().split('\n').filter(Boolean)
    if (todoFiles.length > 0) {
      signals.push({
        id: 'todos',
        title: `处理 TODO (${todoFiles.length} 个文件)`,
        desc: '项目中有标记的 TODO/FIXME 待处理',
        prompt: '帮我找出项目中所有的 TODO 和 FIXME，按优先级列出并逐个解决。',
        tone: 'orange'
      })
    }
  } catch {
    /* no results or grep not available */
  }

  // 6. Fallback: understand project
  const projectName = await readProjectName(cwd)
  if (projectName) {
    const shortName = projectName.length > 16 ? projectName.slice(0, 14) + '…' : projectName
    signals.push({
      id: 'understand',
      title: `了解 ${shortName} 架构`,
      desc: '梳理项目入口、核心模块和关键流程',
      prompt: `帮我快速理解 ${projectName} 项目的整体架构、核心模块和关键流程。`,
      tone: 'blue'
    })
  }

  if (signals.length === 0) return { ok: false, suggestions: null }

  // Shuffle and pick up to 4
  const shuffled = signals.sort(() => Math.random() - 0.5).slice(0, 4)

  // If fewer than 4, pad with generic fillers so the grid always has 4 cards
  const FILLERS: WorkspaceSuggestion[] = [
    {
      id: 'filler-test',
      title: '运行测试并分析',
      desc: '跑一遍测试，分析失败原因并修复',
      prompt: '帮我运行项目的测试套件，分析失败的用例并提出修复方案。',
      tone: 'emerald'
    },
    {
      id: 'filler-review',
      title: '审查最近的改动',
      desc: '对最近的提交做一次 code review',
      prompt: '帮我 review 最近几次提交的代码，找出潜在问题和改进点。',
      tone: 'violet'
    },
    {
      id: 'filler-deps',
      title: '检查依赖健康',
      desc: '看看有没有过时或有安全问题的依赖',
      prompt: '帮我检查项目依赖是否有过时版本或已知安全漏洞，给出升级建议。',
      tone: 'orange'
    },
    {
      id: 'filler-docs',
      title: '补充文档',
      desc: '找出缺少文档的核心模块并补充',
      prompt: '帮我找出项目中缺少文档说明的核心模块，生成简洁的文档。',
      tone: 'blue'
    }
  ]
  const usedIds = new Set(shuffled.map(s => s.id))
  for (const filler of FILLERS) {
    if (shuffled.length >= 4) break
    if (!usedIds.has(filler.id)) shuffled.push(filler)
  }

  shuffled.forEach((s, i) => { s.tone = TONES[i % TONES.length] })

  return { ok: true, suggestions: shuffled }
}
