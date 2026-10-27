import { appendFileSync } from 'node:fs';
import { join } from 'node:path';
export function createCuaClient({ cwd, onElicitation }) {
  const record = event => appendFileSync(join(cwd, 'calls.jsonl'), JSON.stringify(event) + '\n');
  const observations = new Map();
  let actions = [];
  let traceReady = true;
  return {
    instructions: 'Original fixture instructions. Keep all of this.',
    async connect() {},
    publicTools() { return ['js', 'js_reset'].map(name => ({ name, description: `Original ${name}`,
      inputSchema: { type: 'object', properties: { code: { type: 'string' } } } })); },
    async call(name, args, context) {
      // Host trace calls are bookkeeping, not model calls: never recorded.
      if (args.code?.startsWith('if (!globalThis.__deepseekTrace)')) {
        actions = [];
        return { content: [] };
      }
      if (args.code?.startsWith('nodeRepl.write("__DEEPSEEK_TRACE__"')) {
        const trace = traceReady ? { ready: true, tabs: false, actions } : null;
        return { content: [{ type: 'text', text: '__DEEPSEEK_TRACE__' + JSON.stringify(trace) }] };
      }
      if (name === 'js_reset') observations.clear();
      record({ name, args, session: context.sessionId, turn: context.turnId, call: context.toolCallId,
        hostTurn: context.metadata?.['deepseek/host-turn-id'] });
      const bind = args.code?.match(/^globalThis\.__deepseekObservations \?\?= \{\};\nif \(!(.*?)\) \1 = await \((.*)\);$/s);
      if (bind) {
        if (observations.has(bind[1])) return { content: [] };
        const entry = bind[2];
        const app = entry.match(/cua\.getApp\(("(?:[^"\\]|\\.)*")\)/);
        const window = entry.match(/cua\.getApp\(\{windowId: (\d+)\}\)/);
        const tab = entry.match(/cua\.getTab\(("(?:[^"\\]|\\.)*"), \{browser: ("(?:[^"\\]|\\.)*")\}\)/);
        const target = app ? JSON.parse(app[1]) : window ? `window-${window[1]}`
          : { tab_id: JSON.parse(tab[1]), browser: JSON.parse(tab[2]) };
        observations.set(bind[1], target);
        return { content: [{ type: 'text', text: typeof target === 'object'
          ? 'Original browser documentation' : 'Original observation documentation' }] };
      }
      const capture = args.code?.match(/^await (globalThis\.__deepseekObservations\[.*\])\.getAXStateAndScreenshot/);
      if (capture) {
        const appId = observations.get(capture[1]);
        const surface = typeof appId === 'object' ? {kind: 'browserUse'}
          : {kind: 'computerUse', app: {appId}};
        return { content: [{type: 'text', text: 'Window: Fixture\n0 button Save\n1 text Saved'}],
          _meta: {'codex/toolSurface': surface} };
      }
      if (args.code?.startsWith('actions:')) {
        actions = JSON.parse(args.code.slice(8));
        const failed = actions.some(action => action.ok === false);
        return { content: [{ type: 'text', text: failed ? 'Computer Use server error -10005: 7 is an invalid element ID' : 'acted' }], isError: failed };
      }
      if (args.code === 'untraced') traceReady = false;
      if (args.code === 'approve') {
        const response = await onElicitation({ mode: 'form', message: 'Allow fixture?',
          requestedSchema: { type: 'object', properties: {} },
          _meta: { connector_id: 'computer-use', tool_params: { app: 'dev.fixture' }, persist: ['session'] },
        }, { signal: context.signal });
        return { content: [{ type: 'text', text: JSON.stringify(response) }], isError: response.action !== 'accept' };
      }
      if (args.code === 'hang') {
        await new Promise((resolve, reject) => {
          if (context.signal.aborted) { reject(new Error('aborted')); return; }
          context.signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
        });
      }
      if (args.code?.startsWith('surface:')) {
        const appId = args.code.slice(8);
        const surface = appId === 'browser' ? { kind: 'browserUse', backend: 'chrome' }
          : { kind: 'computerUse', app: { appId, kind: 'appId' } };
        return { content: [{ type: 'text', text: 'touched' }], _meta: { 'codex/toolSurface': surface } };
      }
      if (args.code === 'crash') process.exit(8);
      if (args.code?.startsWith('throw:')) return { content: [{ type: 'text', text: args.code.slice(6) }], isError: true };
      return { content: [{ type: 'text', text: args.code ?? 'reset' }], isError: args.code === 'error' };
    },
    async turnEnded(context) { record({ end: context }); return {}; },
    async close() { record({ close: true }); },
  };
}
