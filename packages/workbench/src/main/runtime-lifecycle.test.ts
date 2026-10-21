import { expect, it, vi } from 'vitest'
import { createRuntimeLifecycleQueue, interruptRuntimeStreams } from './runtime-lifecycle'

it('holds concurrent health/start requests behind the entire settings restart', async () => {
  const run = createRuntimeLifecycleQueue()
  const calls: string[] = []
  let ready!: () => void
  const waiting = new Promise<void>(resolve => { ready = resolve })
  const restart = run(async () => { calls.push('stop'); await waiting; calls.push('ready') })
  const reads = Array.from({ length: 5 }, () => run(async () => { calls.push('read') }))
  await Promise.resolve()
  expect(calls).toEqual(['stop'])
  ready()
  await Promise.all([restart, ...reads])
  expect(calls).toEqual(['stop', 'ready', 'read', 'read', 'read', 'read', 'read'])
})

it('does not let a failed restart poison the next recovery attempt', async () => {
  const run = createRuntimeLifecycleQueue()
  await expect(run(async () => { throw new Error('startup failed') })).rejects.toThrow('startup failed')
  await expect(run(async () => 'recovered')).resolves.toBe('recovered')
})

it('notifies each interrupted renderer subscription so it can reconnect', () => {
  const stream = { controller: new AbortController(), stoppedByClient: false, notifyEnd: vi.fn() }
  const streams = new Map([['stream', stream]])
  interruptRuntimeStreams(streams)
  expect(stream.controller.signal.aborted).toBe(true)
  expect(stream.stoppedByClient).toBe(true)
  expect(stream.notifyEnd).toHaveBeenCalledOnce()
  expect(streams.size).toBe(0)
  interruptRuntimeStreams(streams)
  expect(stream.notifyEnd).toHaveBeenCalledOnce()
})
