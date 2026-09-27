"""Synthetic observer dispatch comparison; no shell, HTTP or production edits.

PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/hooks_compare.py
Three independent 10ms sinks, 20 sequential events; ordered, lossless delivery.
"""
import asyncio
import json
import time
from deepseek_tui.integrations.hooks import HookDispatcher, HookSink, ResponseDeltaEvent


class Sink(HookSink):
    def __init__(self):
        self.seen = []
    async def emit(self, event):
        await asyncio.sleep(0.01)
        self.seen.append(int(event.delta))


async def run(mode):
    sinks = [Sink() for _ in range(3)]
    dispatcher = HookDispatcher()
    for sink in sinks:
        dispatcher.add_sink(sink)
    queues = [asyncio.Queue(maxsize=4) for _ in sinks]
    async def worker(queue, sink):
        while True:
            event = await queue.get()
            try:
                if event is None:
                    return
                await sink.emit(event)
            finally:
                queue.task_done()
    workers = [asyncio.create_task(worker(q,s)) for q,s in zip(queues,sinks)] if mode=='bounded_queue' else []
    start = time.perf_counter()
    for i in range(20):
        event = ResponseDeltaEvent(response_id='synthetic', delta=str(i))
        if mode == 'current_serial':
            await dispatcher.emit(event)
        elif mode == 'parallel_sinks':
            await asyncio.gather(*(s.emit(event) for s in sinks))
        else:
            for queue in queues:
                await queue.put(event)
    submitted = time.perf_counter()
    if workers:
        for queue in queues:
            await queue.put(None)
        await asyncio.gather(*workers)
    finished = time.perf_counter()
    assert all(s.seen == list(range(20)) for s in sinks)
    return dict(mode=mode, producer_ms=round((submitted-start)*1000,1),
                drained_ms=round((finished-start)*1000,1), deliveries=60, ordered=True)


async def main():
    print(json.dumps([await run(m) for m in ['current_serial','parallel_sinks','bounded_queue']], indent=2))


if __name__ == '__main__':
    asyncio.run(main())
