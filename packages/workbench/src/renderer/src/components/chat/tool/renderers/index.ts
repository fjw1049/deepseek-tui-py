import { toolRendererRegistry } from '../registry'
import { ShellRenderer } from './shell'
import { FileEditRenderer } from './file-edit'
import { ReadRenderer } from './read'
import { ListRenderer } from './list'
import { SubagentRenderer } from './subagent'

/**
 * Tool renderer registration station. Mirrors Tanzo's `renderers/index.ts`:
 * registering a new tool UI = adding one entry here. The card host never
 * changes; it just resolves whatever the registry holds.
 */
export function registerToolRenderers(): void {
  // File mutations → inline diff
  toolRendererRegistry.registerMany({
    write_file: FileEditRenderer,
    edit_file: FileEditRenderer,
    apply_patch: FileEditRenderer
  })

  // Shell / command execution → streaming terminal
  toolRendererRegistry.registerMany({
    exec_shell: ShellRenderer,
    exec_shell_wait: ShellRenderer,
    exec_shell_interact: ShellRenderer,
    run_terminal_cmd: ShellRenderer
  })

  // Read-only file/web content → scrollable text panel
  toolRendererRegistry.registerMany({
    read_file: ReadRenderer,
    fetch_url: ReadRenderer,
    web_search: ReadRenderer
  })

  // Line-oriented search/listing → aligned rows with match highlighting
  toolRendererRegistry.registerMany({
    list_dir: ListRenderer,
    grep: ListRenderer,
    grep_files: ListRenderer,
    search_files: ListRenderer,
    glob_file_search: ListRenderer,
    file_search: ListRenderer
  })

  // Sub-agent orchestration → calm one-line marker (Bot icon + agent descriptor).
  // Deliberately lighter than the durable-task UI; rich live progress is the
  // mailbox-driven SubagentSummaryPanel's job.
  toolRendererRegistry.registerMany({
    agent_spawn: SubagentRenderer,
    spawn_agent: SubagentRenderer,
    delegate_to_agent: SubagentRenderer,
    agent_wait: SubagentRenderer,
    agent_result: SubagentRenderer,
    agent_cancel: SubagentRenderer,
    agent_list: SubagentRenderer
  })
}
