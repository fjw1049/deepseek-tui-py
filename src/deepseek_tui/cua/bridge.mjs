// Host-only bridge. stdout is framed JSON; model code only reaches client.call.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

let client;
let sequence = 0;
let closing = false;
const approvals = new Map();
const calls = new Map();
const send = value => process.stdout.write(`${JSON.stringify(value)}\n`);

async function handle(request) {
  switch (request.type) {
    case 'connect': {
      if (client) throw new Error('Already connected');
      const { createCuaClient } = await import(pathToFileURL(request.clientPath).href);
      client = createCuaClient({
        command: request.command, cwd: request.cwd, adapter: 'deepseek-workbench',
        onElicitation: (params, { signal }) => new Promise(resolve => {
          const id = ++sequence;
          const finish = response => {
            approvals.delete(id);
            signal.removeEventListener('abort', abort);
            resolve(response);
          };
          const abort = () => { finish({ action: 'cancel' }); send({ type: 'elicitationCancelled', id }); };
          if (signal.aborted) { resolve({ action: 'cancel' }); return; }
          approvals.set(id, finish);
          signal.addEventListener('abort', abort, { once: true });
          send({ type: 'elicitation', id, params });
        }),
      });
      await client.connect();
      return { instructions: client.instructions, tools: client.publicTools() };
    }
    case 'call': {
      if (!client) throw new Error('Not connected');
      const controller = new AbortController();
      calls.set(request.id, controller);
      try {
        const result = await client.call(request.name, request.arguments, {
          ...request.context, signal: controller.signal,
        });
        return { ...result, instructions: client.instructions, tools: client.publicTools() };
      } finally { calls.delete(request.id); }
    }
    case 'interrupt':
      for (const controller of calls.values()) controller.abort();
      for (const finish of [...approvals.values()]) finish({ action: 'cancel' });
      return { interrupted: true };
    case 'endTurn':
      return await client?.turnEnded(request.context) ?? {};
    case 'close':
      closing = true;
      for (const controller of calls.values()) controller.abort();
      for (const finish of [...approvals.values()]) finish({ action: 'cancel' });
      await client?.close();
      return { closed: true };
    default: throw new Error('Unknown host request');
  }
}

const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
input.on('line', line => {
  let request;
  try { request = JSON.parse(line); } catch { return; }
  if (request.type === 'elicitationResponse') {
    approvals.get(request.id)?.(request.response);
    return;
  }
  if (closing) return;
  // Do not queue control messages behind a call waiting for a human.
  handle(request).then(result => send({ id: request.id, ok: true, result }),
    error => send({ id: request.id, ok: false, error: String(error.message ?? error) }));
});
input.on('close', async () => {
  closing = true;
  for (const controller of calls.values()) controller.abort();
  for (const finish of [...approvals.values()]) finish({ action: 'cancel' });
  await client?.close();
});
