export function isMarkdownPath(path: string): boolean {
  const fileName = path.split(/[/\\]/).pop() ?? path
  const ext = fileName.includes('.') ? fileName.split('.').pop()?.toLowerCase() : ''
  return ext === 'md' || ext === 'markdown'
}

export function languageForPath(path: string): string {
  const fileName = path.split(/[/\\]/).pop() ?? path
  const ext = fileName.includes('.') ? fileName.split('.').pop()?.toLowerCase() : ''
  const named: Record<string, string> = {
    dockerfile: 'dockerfile', containerfile: 'dockerfile',
    '.bashrc': 'shell', '.zshrc': 'shell', '.profile': 'shell',
    '.gitignore': 'ini', '.gitattributes': 'ini', '.editorconfig': 'ini'
  }
  const extra: Record<string, string> = {
    java: 'java', c: 'c', h: 'cpp', cc: 'cpp', cpp: 'cpp', cxx: 'cpp', hpp: 'cpp',
    cs: 'csharp', sql: 'sql', rb: 'ruby', php: 'php', swift: 'swift',
    kt: 'kotlin', kts: 'kotlin', dart: 'dart', lua: 'lua', r: 'r',
    ps1: 'powershell', bat: 'bat', cmd: 'bat', zsh: 'shell',
    jsonc: 'json', jsonl: 'json', ndjson: 'json', mts: 'typescript', cts: 'typescript',
    pyi: 'python', pyw: 'python', ini: 'ini', cfg: 'ini', properties: 'ini',
    graphql: 'graphql', gql: 'graphql', proto: 'protobuf', tf: 'hcl', hcl: 'hcl',
    vue: 'html', svelte: 'html', mdx: 'mdx', rst: 'restructuredtext'
  }
  const name = fileName.toLowerCase()
  if (named[name]) return named[name]!
  if (/^(dockerfile|containerfile)\./.test(name)) return 'dockerfile'
  if (/^\.env(?:\.|$)/.test(name)) return 'ini'
  if (ext && extra[ext]) return extra[ext]!
  switch (ext) {
    case 'ts':
    case 'tsx':
      return 'typescript'
    case 'js':
    case 'jsx':
    case 'mjs':
    case 'cjs':
      return 'javascript'
    case 'json':
      return 'json'
    case 'md':
    case 'markdown':
      return 'markdown'
    case 'py':
      return 'python'
    case 'css':
      return 'css'
    case 'scss':
      return 'scss'
    case 'less':
      return 'less'
    case 'html':
    case 'htm':
      return 'html'
    case 'yaml':
    case 'yml':
      return 'yaml'
    case 'xml':
      return 'xml'
    case 'sh':
    case 'bash':
      return 'shell'
    case 'go':
      return 'go'
    case 'rs':
      return 'rust'
    case 'toml':
      return 'ini'
    default:
      return 'plaintext'
  }
}
