// Host-only bridge. stdout is framed JSON; model code only reaches client.call.
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

let client;
let sequence = 0;
let closing = false;
const approvals = new Map();
const calls = new Map();
const send = value => process.stdout.write(`${JSON.stringify(value)}\n`);

// Host code, idempotent per REPL: wraps targets the runtime returns so each UI input a call
// dispatches, and each UI state it reads, is recorded. The host then knows what model code
// did without parsing it.
const INPUTS = ['click', 'drag', 'scroll', 'selectText', 'setValue', 'performSecondaryAction', 'paste',
  'pressKey', 'typeText', 'typeCharacters', 'goto', 'back', 'forward', 'reload', 'close'];
const OBSERVATIONS = ['getAXState', 'getScreenshot', 'getAXStateAndScreenshot'];
const TRACE_INSTALL = `if (!globalThis.__deepseekTrace) {
  const trace = globalThis.__deepseekTrace = [];
  const api = globalThis.cua;
  const record = (entry, run) => {
    trace.push(entry);
    return Promise.resolve().then(run).then(
      value => { entry.ok = true; return value; }, error => { entry.ok = false; throw error; });
  };
  const wrap = target => {
    if (target === null || typeof target !== 'object' || Object.hasOwn(target, '__deepseekTraced')) return target;
    for (const name of [...${JSON.stringify(INPUTS)}, ...${JSON.stringify(OBSERVATIONS)}]) {
      const original = target[name];
      if (typeof original !== 'function') continue;
      const observe = ${JSON.stringify(OBSERVATIONS)}.includes(name);
      target[name] = function (...args) {
        return record(observe ? { action: name, observe } : { action: name,
          coordinate: ['click', 'drag', 'scroll'].includes(name) && Array.isArray(args[0]) },
        () => original.apply(this, args));
      };
    }
    // DOM tabs also take input through Playwright locators: record each use as possible input.
    if ('playwright' in target) {
      const playwright = target.playwright;
      Object.defineProperty(target, 'playwright', { configurable: true,
        get() { trace.push({ action: 'playwright' }); return playwright; } });
    }
    Object.defineProperty(target, '__deepseekTraced', { value: true });
    return target;
  };
  for (const name of ['getApp', 'getTab', 'createBrowserTab']) {
    const original = api?.[name];
    if (typeof original !== 'function') continue;
    api[name] = async function (...args) {
      // Binding prints the target's current state, so it is an observation too.
      const target = await record({ action: name, observe: true }, () => original.apply(this, args));
      // Only a tab that exists can take Playwright input outside the wrappers.
      if (name !== 'getApp') globalThis.__deepseekTabs = true;
      return wrap(target);
    };
  }
  globalThis.__deepseekTraceReady = typeof api?.getApp === 'function' || typeof api?.getTab === 'function';
}
globalThis.__deepseekTrace.length = 0;`;
const TRACE_MARK = '__DEEPSEEK_TRACE__';
const TRACE_READ = `nodeRepl.write(${JSON.stringify(TRACE_MARK)} + JSON.stringify(globalThis.__deepseekTrace
  ? { ready: Boolean(globalThis.__deepseekTraceReady), tabs: Boolean(globalThis.__deepseekTabs),
      actions: globalThis.__deepseekTrace.splice(0) } : null));`;
const NATIVE_APP_HINT = 'On Linux and Windows, observe a window: pass window_id from cua.getState().';
// A localized display name (文本编辑 for TextEdit) is not an app id. Resolve it from the runtime's
// own inventory, and only when the runtime rejected the name itself: a denial is never retried.
const OPEN_APP = `async name => {
  try { return await cua.getApp(name); } catch (error) {
    if (!/^Invalid app:/.test(String(error?.message))) throw error;
    const wanted = name.toLowerCase();
    const found = (await cua.listApps({ emit: false })).filter(app =>
      app.id.toLowerCase() === wanted || app.displayName?.toLowerCase() === wanted);
    if (found.length !== 1) throw error;
    return await cua.getApp(found[0].id);
  }
}`;

// Host calls that print nothing still return an empty text block; never pass those on.
const printed = result => (result.content ?? []).filter(b => b.type !== 'text' || b.text.trim());

function readTrace(result) {
  if (result.isError) return null;
  for (const block of result.content ?? []) {
    const at = block.type === 'text' ? block.text.indexOf(TRACE_MARK) : -1;
    if (at < 0) continue;
    try { return JSON.parse(block.text.slice(at + TRACE_MARK.length).split('\n')[0]); } catch { return null; }
  }
  return null;
}

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
          const { app, window_id: windowId, browser, tab_id } = request.arguments;
          const target = app ? { app } : windowId !== undefined ? { window_id: windowId } : { browser, tab_id };
          // Native apps take a name on macOS but an open window elsewhere.
          const entry = app
            ? `(cua.computer?.target ?? "mac") === "mac" ? (${OPEN_APP})(${JSON.stringify(app)})`
              + ` : Promise.reject(new Error(${JSON.stringify(NATIVE_APP_HINT)}))`
            : windowId !== undefined ? `cua.getApp({windowId: ${Number(windowId)}})`
            : `cua.getTab(${JSON.stringify(tab_id)}, {browser: ${JSON.stringify(browser)}})`;
          // Bind once per REPL: binding already prints the full tree, so rebinding on every
          // observation would send it twice. A reset REPL loses the cache with its bindings.
          const slot = `globalThis.__deepseekObservations[${JSON.stringify(JSON.stringify(target))}]`;
          const first = await client.call('js', {
            code: `globalThis.__deepseekObservations ??= {};\nif (!${slot}) ${slot} = await (${entry});`,
          }, { ...context, toolCallId: `${context.toolCallId}:bind` });
          if (first.isError) result = first;
          else {
            result = await client.call('js', {
              code: `await ${slot}.getAXStateAndScreenshot({disableDiffing: true});`,
            }, context);
            if (result.isError) {
              // A closed tab or window must not stay cached.
              await client.call('js', { code: `delete ${slot};` },
                { ...context, toolCallId: `${context.toolCallId}:unbind` }).catch(() => {});
            }
            const text = (result.content ?? []).filter(b => b.type === 'text').map(b => b.text).join('\n');
            const images = (result.content ?? []).filter(b => b.type === 'image');
            // The observation is captured before joining documentation/entry-point output.
            // The host judges completeness and expected text from it (cua/tools.py).
            result.observation = { target, text };
            result.content = [...printed(first), ...(result.content ?? [])];
            if (!text.trim() && !images.length) {
              result.isError = true;
              result.content.push({ type: 'text', text: 'No observation returned. Do not act on old state.' });
            }
          }
        } else if (request.name === 'js') {
          const install = await client.call('js', { code: TRACE_INSTALL },
            { ...context, toolCallId: `${context.toolCallId}:trace` });
          result = await client.call(request.name, request.arguments, context);
          if (!controller.signal.aborted) {
            const read = await client.call('js', { code: TRACE_READ },
              { ...context, toolCallId: `${context.toolCallId}:trace` });
            result.trace = readTrace(read);
          }
          // A fresh REPL prints its first-use documentation on its first call, which may be
          // the install call; the model must still receive it.
          if (!install.isError) result.content = [...printed(install), ...(result.content ?? [])];
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
