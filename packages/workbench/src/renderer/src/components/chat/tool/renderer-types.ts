import type { ToolRenderContext } from './render-context'

/**
 * A tool renderer is a set of slot components, not a single component. The
 * `ToolCard` host builds the context, resolves a renderer, and renders the
 * returned slots inside a collapsible shell. Registering a new tool = adding
 * one entry to the registry; the card host never changes.
 */
export interface ToolRenderer {
  /** Compact header row (icon + label + status + descriptor). Always shown. */
  Header?: React.ComponentType<{ context: ToolRenderContext }>

  /** Body shown when expanded (diff, stdout, hit list…). */
  Output?: React.ComponentType<{ context: ToolRenderContext }>

  /** Optional footer below the output (exit code, duration…). */
  Footer?: React.ComponentType<{ context: ToolRenderContext }>

  /** Render the output area even while the tool is still running. */
  renderWhenPending?: boolean

  /** Let the output fill the card edge-to-edge (no inner padding). */
  fullBleed?: boolean
}

export type BoundRenderer = ToolRenderer
