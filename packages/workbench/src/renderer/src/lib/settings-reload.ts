/** Re-read MCP config from disk and reconnect enabled servers when runtime is up. */
export async function reloadMcpWithRuntime(loadFromDisk: () => Promise<unknown>): Promise<{
  disk: boolean
  runtime: boolean
}> {
  await loadFromDisk()
  if (typeof window.dsGui?.runtimeRequest !== 'function') {
    return { disk: true, runtime: false }
  }
  try {
    const health = await window.dsGui.runtimeRequest('/health', 'GET')
    if (!health.ok) {
      return { disk: true, runtime: false }
    }
    const startup = await window.dsGui.runtimeRequest('/mcp/startup', 'POST')
    return { disk: true, runtime: startup.ok }
  } catch {
    return { disk: true, runtime: false }
  }
}
