// Setup check: does the runtime reach the user's Chrome through its extension? Lists browsers
// only; never reads tabs, pages or the desktop. Prints one JSON line: {connected, reason?}.
import { pathToFileURL } from 'node:url';

const [clientPath, executable] = process.argv.slice(2);
const print = value => process.stdout.write(`${JSON.stringify(value)}\n`);
let client;
try {
  const { createCuaClient } = await import(pathToFileURL(clientPath).href);
  client = createCuaClient({ command: [executable, '--chrome'], cwd: process.cwd(),
    adapter: 'deepseek-workbench-setup', onElicitation: async () => ({ action: 'cancel' }) });
  await client.connect();
  const context = { sessionId: 'deepseek-setup-check', turnId: `setup-${Date.now()}`, toolCallId: 'browsers' };
  const result = await client.call('js', {
    code: 'nodeRepl.write("@@" + JSON.stringify((await cua.listBrowsers({ emit: false })).map(b => b.family)))',
  }, context);
  const text = (result.content ?? []).filter(b => b.type === 'text').map(b => b.text).join('\n');
  const marked = text.lastIndexOf('@@');
  const families = marked >= 0 ? JSON.parse(text.slice(marked + 2).split('\n')[0]) : [];
  print(result.isError || marked < 0 ? { connected: false, reason: 'runtime' }
    : families.includes('chrome') ? { connected: true } : { connected: false, reason: 'extension' });
  await client.turnEnded({ sessionId: context.sessionId, turnId: context.turnId, event: 'Stop' }).catch(() => {});
} catch {
  print({ connected: false, reason: 'runtime' });
} finally {
  await client?.close().catch(() => {});
}
