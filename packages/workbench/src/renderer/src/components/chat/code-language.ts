import { languageForPath } from '../../lib/monaco-language-for-path'

const LANGUAGE_ALIASES: Record<string, string> = {
  csharp: 'cs',
  docker: 'dockerfile',
  plaintext: '',
  shellscript: 'shell',
  text: '',
  typescriptreact: 'tsx',
  javascriptreact: 'jsx'
}

export function normalizeLanguage(language: string): string {
  const raw = language.trim().toLowerCase()
  return LANGUAGE_ALIASES[raw] ?? raw
}

// Monaco ships no grammar for these, so `languageForPath` gives up on them —
// but Shiki (the chat surface) has one, and a bare name is all it needs.
const SHIKI_ONLY_LANGUAGES: Record<string, string> = {
  makefile: 'makefile',
  gnumakefile: 'makefile',
  'cmakelists.txt': 'cmake'
}

export function languageFromPath(path: string | undefined): string {
  if (!path) return ''
  const name = path.split(/[\\/]/).pop() ?? ''
  const ext = name.includes('.') ? name.split('.').pop()?.toLowerCase() ?? '' : ''
  // Shiki has dedicated grammars where Monaco uses a compatible fallback.
  if (['tsx', 'jsx', 'vue', 'svelte', 'toml', 'jsonc'].includes(ext)) return ext
  const shikiOnly = SHIKI_ONLY_LANGUAGES[name.toLowerCase()]
  if (shikiOnly) return shikiOnly
  const language = languageForPath(path)
  return language === 'plaintext' ? ext : normalizeLanguage(language)
}

export function titleFromPath(path: string | undefined): string | undefined {
  if (!path?.trim()) return undefined
  return path.trim()
}
