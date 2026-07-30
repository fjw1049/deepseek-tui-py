const LANGUAGE_ALIASES: Record<string, string> = {
  csharp: 'cs',
  docker: 'dockerfile',
  plaintext: '',
  shellscript: 'shell',
  text: '',
  typescriptreact: 'tsx',
  javascriptreact: 'jsx'
}

const EXT_TO_LANGUAGE: Record<string, string> = {
  c: 'c',
  cpp: 'cpp',
  cs: 'cs',
  css: 'css',
  go: 'go',
  html: 'html',
  htm: 'html',
  java: 'java',
  js: 'js',
  jsx: 'jsx',
  json: 'json',
  md: 'md',
  mjs: 'js',
  php: 'php',
  py: 'python',
  rb: 'rb',
  rs: 'rust',
  sh: 'shell',
  sql: 'sql',
  swift: 'swift',
  ts: 'typescript',
  tsx: 'tsx',
  xml: 'xml',
  yaml: 'yaml',
  yml: 'yaml'
}

export function normalizeLanguage(language: string): string {
  const raw = language.trim().toLowerCase()
  return LANGUAGE_ALIASES[raw] ?? raw
}

export function languageFromPath(path: string | undefined): string {
  if (!path) return ''
  const base = path.split(/[\\/]/).pop() ?? path
  const dot = base.lastIndexOf('.')
  if (dot < 0) return ''
  const ext = base.slice(dot + 1).toLowerCase()
  return EXT_TO_LANGUAGE[ext] ?? ext
}

export function titleFromPath(path: string | undefined): string | undefined {
  if (!path?.trim()) return undefined
  return path.trim()
}
