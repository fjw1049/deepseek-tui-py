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
    case 'call':
    case 'observe': {
      if (!client) throw new Error('Not connected');
      const controller = new AbortController();
      calls.set(request.id, controller);
      try {
        const context = { ...request.context, signal: controller.signal };
        let result;
        if (request.type === 'observe') {
          // Only host-written observation code runs here. Never classify arbitrary JS as read-only.
          const { app, browser, tab_id } = request.arguments;
          const entry = app
            ? `cua.getApp(${JSON.stringify(app)})`
            : `cua.getTab(${JSON.stringify(tab_id)}, {browser: ${JSON.stringify(browser)}})`;
          const binding = `__deepseekObservation${request.id}`;
          const first = await client.call('js', { code: `var ${binding} = await ${entry};` },
            { ...context, toolCallId: `${context.toolCallId}:bind` });
          if (first.isError) result = first;
          else {
            result = await client.call('js', {
              code: `await ${binding}.getAXStateAndScreenshot({disableDiffing: true});`,
            }, context);
            const text = (result.content ?? []).filter(b => b.type === 'text').map(b => b.text).join('\n');
            const images = (result.content ?? []).filter(b => b.type === 'image');
            // The observation is captured before joining documentation/entry-point output.
            const ranges = [...text.matchAll(/\(showing \d+-(\d+) of (\d+) items\)/g)];
            result.observation = { target: app ? {app} : {browser, tab_id}, text,
              complete: !ranges.some(([, shown, total]) => Number(shown) < Number(total)),
              expectations: (request.arguments.expect ?? []).map(expected => ({
                text: expected, matched: text.includes(expected),
              })) };
            result.content = [...(first.content ?? []), ...(result.content ?? [])];
            if (!text.trim() && !images.length) {
              result.isError = true;
              result.content.push({ type: 'text', text: 'No observation returned. Do not act on old state.' });
            }
          }
        } else {
          result = await client.call(request.name, request.arguments, context);
        }
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
