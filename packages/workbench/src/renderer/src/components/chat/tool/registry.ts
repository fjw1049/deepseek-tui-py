import type { ToolRenderContext } from './render-context'
import type { ToolRenderer } from './renderer-types'

/**
 * Four-layer resolver (matches Tanzo's registry shape). Resolution priority:
 * exact `toolName` → `shortName` → dynamic prefix (`mcp__`). Returns null when
 * nothing matches, in which case the card host renders a default header/output.
 */
class ToolRendererRegistry {
  private byName = new Map<string, ToolRenderer>()
  private dynamicHandlers = new Map<string, ToolRenderer>()

  register(name: string, renderer: ToolRenderer): void {
    this.byName.set(name, renderer)
  }

  registerMany(entries: Record<string, ToolRenderer>): void {
    for (const [name, renderer] of Object.entries(entries)) {
      this.register(name, renderer)
    }
  }

  registerDynamicPrefix(prefix: string, renderer: ToolRenderer): void {
    this.dynamicHandlers.set(prefix, renderer)
  }

  resolve(context: ToolRenderContext): ToolRenderer | null {
    const exact = this.byName.get(context.toolName)
    if (exact) return exact
    const short = this.byName.get(context.shortName)
    if (short) return short
    for (const [prefix, renderer] of this.dynamicHandlers) {
      if (context.toolName.startsWith(`${prefix}__`)) return renderer
    }
    return null
  }

  listNames(): string[] {
    return [...this.byName.keys()]
  }
}

export const toolRendererRegistry = new ToolRendererRegistry()

export function resolveToolRenderer(
  context: ToolRenderContext
): ToolRenderer | null {
  return toolRendererRegistry.resolve(context)
}
