const TREE_MARK_RE = /(?:^|[\s])(?:├──|└──|│|──)/u
const INDENT_PATH_RE = /^(?: {2}|\t)+[A-Za-z0-9_./@-][\w./@+-]*(?:\s|$)/u

/**
 * Heuristic: unlabeled / plaintext fences that are ASCII directory trees
 * should not render as fake "text" source-code cards.
 */
export function looksLikeStructureTree(code: string, language = ''): boolean {
  const lang = language.trim().toLowerCase()
  if (lang && !['text', 'plaintext', 'txt', 'plain'].includes(lang)) return false

  const lines = code
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map((line) => line.replace(/\s+$/u, ''))
    .filter((line) => line.trim().length > 0)
  if (lines.length < 2) return false

  let treeMarks = 0
  let indentedPaths = 0
  for (const line of lines) {
    if (TREE_MARK_RE.test(line)) treeMarks += 1
    else if (INDENT_PATH_RE.test(line)) indentedPaths += 1
  }

  if (treeMarks >= 2) return true
  // Soft trees without box-drawing chars (spaces + path-like names).
  return treeMarks + indentedPaths >= Math.min(3, lines.length) && indentedPaths >= 2
}
