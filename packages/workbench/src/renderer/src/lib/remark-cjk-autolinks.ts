import type { Root } from 'mdast'
import type { VFile } from 'vfile'
import { visit } from 'unist-util-visit'

/** GFM bare links otherwise consume adjacent Chinese punctuation and prose. */
export function remarkCjkAutolinks() {
  return (tree: Root, file: VFile): void => {
    const source = String(file.value)
    visit(tree, 'link', (node, index, parent) => {
      const start = node.position?.start.offset
      if (start === undefined || index === undefined || !parent) return
      // Explicit Markdown links and angle-bracket autolinks own their boundaries.
      if (!/^(?:https?:\/\/|www\.)/i.test(source.slice(start))) return
      const label = node.children.length === 1 ? node.children[0] : undefined
      if (label?.type !== 'text') return
      const boundary = label.value.search(/[，。！？；：、（）【】《》〈〉「」『』“”‘’]/)
      if (boundary < 0) return
      const suffix = label.value.slice(boundary)
      label.value = label.value.slice(0, boundary)
      node.url = node.url.slice(0, node.url.length - suffix.length)
      parent.children.splice(index + 1, 0, { type: 'text', value: suffix })
    })
  }
}
