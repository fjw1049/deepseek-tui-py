/** Serialize starts and settings restarts so only one owner can stop/spawn the runtime. */
export function createRuntimeLifecycleQueue(): <T>(operation: () => Promise<T>) => Promise<T> {
  let tail: Promise<unknown> = Promise.resolve()
  return <T>(operation: () => Promise<T>): Promise<T> => {
    const result = tail.then(operation, operation)
    tail = result.catch(() => undefined)
    return result
  }
}

export type RuntimeStream = {
  controller: AbortController
  stoppedByClient: boolean
  notifyEnd: () => void
}

export function interruptRuntimeStreams(streams: Map<string, RuntimeStream>): void {
  for (const stream of streams.values()) {
    stream.stoppedByClient = true
    stream.controller.abort()
    // End the renderer's current subscription so its reconnect loop can resume.
    stream.notifyEnd()
  }
  streams.clear()
}
