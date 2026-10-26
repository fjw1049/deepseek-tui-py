import { appendFileSync } from 'node:fs';
import { join } from 'node:path';
export function createCuaClient({ cwd, onElicitation }) {
  const record = event => appendFileSync(join(cwd, 'calls.jsonl'), JSON.stringify(event) + '\n');
  const observations = new Map();
  return {
    instructions: 'Original fixture instructions. Keep all of this.',
    async connect() {},
    publicTools() { return ['js', 'js_reset'].map(name => ({ name, description: `Original ${name}`,
      inputSchema: { type: 'object', properties: { code: { type: 'string' } } } })); },
    async call(name, args, context) {
      record({ name, args, session: context.sessionId, turn: context.turnId, call: context.toolCallId,
        hostTurn: context.metadata?.['deepseek/host-turn-id'] });
      const binding = args.code?.match(/^var (__deepseekObservation\d+) = await cua\.getApp\((.*)\);$/);
      if (binding) {
        observations.set(binding[1], JSON.parse(binding[2]));
        return { content: [{type: 'text', text: 'Original observation documentation'}] };
      }
      const tab = args.code?.match(/^var (__deepseekObservation\d+) = await cua\.getTab\((.*), \{browser: (.*)\}\);$/);
      if (tab) {
        observations.set(tab[1], {tab_id: JSON.parse(tab[2]), browser: JSON.parse(tab[3])});
        return { content: [{type: 'text', text: 'Original browser documentation'}] };
      }
      const capture = args.code?.match(/^await (__deepseekObservation\d+)\.getAXStateAndScreenshot/);
      if (capture) {
        const appId = observations.get(capture[1]);
        const surface = typeof appId === 'object' ? {kind: 'browserUse'}
          : {kind: 'computerUse', app: {appId}};
        return { content: [{type: 'text', text: 'Window: Fixture\n0 button Save\n1 text Saved'}],
          _meta: {'codex/toolSurface': surface} };
      }
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
