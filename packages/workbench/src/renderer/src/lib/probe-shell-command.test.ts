import { describe, expect, it } from 'vitest'
import {
  hasUnsafeShellRedirect,
  isProbeShellCommand,
  splitCompoundCommands
} from './probe-shell-command'

describe('splitCompoundCommands', () => {
  it('splits && ; | and keeps quoted text intact', () => {
    expect(
      splitCompoundCommands('ls -la && echo "a && b" | head -5; git log --oneline -5')
    ).toEqual(['ls -la', 'echo "a && b"', 'head -5', 'git log --oneline -5'])
  })
})

describe('hasUnsafeShellRedirect', () => {
  it('allows /dev/null redirects', () => {
    expect(hasUnsafeShellRedirect('git log 2>/dev/null')).toBe(false)
    expect(hasUnsafeShellRedirect('ls >/dev/null')).toBe(false)
  })

  it('rejects file redirects and heredocs', () => {
    expect(hasUnsafeShellRedirect('echo hi > out.txt')).toBe(true)
    expect(hasUnsafeShellRedirect("python3 <<'PY'\nprint(1)\nPY")).toBe(true)
  })

  it('rejects fd-numbered redirects to a real file but keeps fd dup', () => {
    expect(hasUnsafeShellRedirect('echo hi 2> err.txt')).toBe(true)
    expect(hasUnsafeShellRedirect('echo hi 1> out.txt')).toBe(true)
    expect(hasUnsafeShellRedirect('ls -la 2>&1')).toBe(false)
    expect(hasUnsafeShellRedirect('git log 2>/dev/null')).toBe(false)
  })
})

describe('isProbeShellCommand', () => {
  it('accepts exploratory compounds like the dialogue-stage screenshot', () => {
    expect(
      isProbeShellCommand(
        'ls -la && echo "---FILES---" && find . -maxdepth 2 -type f -not -path "./.git/*"'
      )
    ).toBe(true)
    expect(
      isProbeShellCommand(
        'echo "---GIT---" && git log --oneline -5 2>/dev/null; echo "---LANGS---"'
      )
    ).toBe(true)
  })

  it('accepts common read-only git / list probes', () => {
    expect(isProbeShellCommand('git status -sb')).toBe(true)
    expect(isProbeShellCommand('git diff --stat')).toBe(true)
    expect(isProbeShellCommand('git stash list')).toBe(true)
    expect(isProbeShellCommand('pwd && ls')).toBe(true)
  })

  it('rejects mutating or unknown commands', () => {
    expect(isProbeShellCommand('git commit -m "x"')).toBe(false)
    expect(isProbeShellCommand('git stash push -m "wip"')).toBe(false)
    expect(isProbeShellCommand('rm -rf dist')).toBe(false)
    expect(isProbeShellCommand('npm install')).toBe(false)
    expect(isProbeShellCommand('npm test')).toBe(false)
    expect(isProbeShellCommand('sed -i "" "s/a/b/" foo.ts')).toBe(false)
    expect(isProbeShellCommand("python3 <<'PY'\nopen('a','w').write('x')\nPY")).toBe(false)
    expect(isProbeShellCommand('ls && npm install')).toBe(false)
    expect(isProbeShellCommand('')).toBe(false)
    expect(isProbeShellCommand(undefined)).toBe(false)
  })

  it('accepts version / list package probes only', () => {
    expect(isProbeShellCommand('node --version')).toBe(true)
    expect(isProbeShellCommand('npm ls')).toBe(true)
    expect(isProbeShellCommand('pip show requests')).toBe(true)
  })

  it('accepts read-only find but rejects mutating find actions', () => {
    expect(isProbeShellCommand('find . -name "*.ts"')).toBe(true)
    expect(isProbeShellCommand('find . -type f -maxdepth 2')).toBe(true)
    expect(isProbeShellCommand('find . -delete')).toBe(false)
    expect(isProbeShellCommand('find . -type f -exec rm {} +')).toBe(false)
    expect(isProbeShellCommand('find . -execdir rm {} +')).toBe(false)
    expect(isProbeShellCommand('find . -fprintf out.txt "%p"')).toBe(false)
  })

  it('rejects command / process substitution that hides a mutating command', () => {
    expect(isProbeShellCommand('echo $(rm -rf /tmp/x)')).toBe(false)
    expect(isProbeShellCommand('cat `rm foo`')).toBe(false)
    expect(isProbeShellCommand('grep x <(cat y)')).toBe(false)
  })

  it('rejects fd-numbered redirects to a real file', () => {
    expect(isProbeShellCommand('echo hi 2> err.txt')).toBe(false)
    expect(isProbeShellCommand('echo hi 1> out.txt')).toBe(false)
  })
})
