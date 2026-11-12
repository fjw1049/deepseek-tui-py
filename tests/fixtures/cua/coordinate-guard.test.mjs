import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createCoordinateGuard } from '../../../src/deepseek_tui/cua/coordinate-guard.mjs';

// Exercise the production REPL wrapper and actual host mailbox together, not a copied guard.
test('coordinate input is bound to each screenshot and checked at each input', async () => {
  const frames = new Map([['dev.a', [1, 0, 0, 600, 400]], ['dev.b', [2, 0, 0, 600, 400]]]);
  let duringCapture = () => {}, userChanged = false;
  const sent = [];
  const guard = await createCoordinateGuard('', async () => Object.fromEntries([...frames].map(([app, frame]) => [app, frame ? [frame] : []])));
  try {
    const source = await readFile(new URL('../../../src/deepseek_tui/cua/bridge.mjs', import.meta.url), 'utf8');
    const install = (0, eval)(source.slice(source.indexOf('const INPUTS'), source.indexOf('const TRACE_MARK')) + '\nTRACE_INSTALL');
    globalThis.__deepseekCoordinatePath = guard.path;
    guard.start();
    globalThis.cua = { async getApp(id) { return {
      async click(target) { if (userChanged) throw Error('state_changed'); sent.push([id, target]); },
      async drag(from) { sent.push([id, from]); },
      async scroll(target) { sent.push([id, target]); },
      async getScreenshot() { userChanged = false; duringCapture(); return new Uint8Array(4); },
      async getAXStateAndScreenshot() { duringCapture(); return { screenshot: new Uint8Array(4) }; },
      async getAXState() { return 'tree'; }
    }; } };
    await new (Object.getPrototypeOf(async () => {}).constructor)(install)();
    const a = await cua.getApp('dev.a'), b = await cua.getApp('dev.b');
    await assert.rejects(a.click([1, 2]), /Coordinate guard/); // No observed pixels.
    await a.getScreenshot(); await b.getAXState();
    await a.click([1, 2]); // Reading B must not steal A's snapshot.
    await assert.rejects(b.click([1, 2]), /Coordinate guard/);
    frames.set('dev.a', [1, 20, 0, 600, 400]);
    for (const action of [() => a.click([1, 2]), () => a.drag([1, 2], [3, 4]), () => a.scroll([1, 2], 'down')]) {
      await assert.rejects(action(), /Coordinate guard/);
    }
    await a.click(3); // Index operations do not depend on a screenshot.
    await a.getAXState(); await assert.rejects(a.click([1, 2]), /Coordinate guard/);
    await a.getScreenshot(); await a.click([1, 2]); // Same-call explicit screenshot recovers.
    // Same bounds, different window must invalidate too.
    frames.set('dev.a', [9, 20, 0, 600, 400]);
    await assert.rejects(a.click([1, 2]), /Coordinate guard/);
    duringCapture = () => frames.set('dev.a', [9, 20, 0, 800, 400]);
    await assert.rejects(a.getScreenshot(), /window changed during screenshot/);
    await assert.rejects(a.click([1, 2]), /Coordinate guard/);
    duringCapture = () => {};
    await a.getAXStateAndScreenshot();
    // Geometry validation must not observe the runtime and clear its user-change guard.
    userChanged = true;
    await assert.rejects(a.click([1, 2]), /state_changed/);
    userChanged = false;
    frames.set('dev.a', null);
    await assert.rejects(a.click([1, 2]), /geometry unavailable/);
    frames.set('dev.a', [9, 20, 0, 800, 400]);
    await a.getScreenshot();
    frames.set('dev.a', [10, 20, 0, 800, 400]);
    await assert.rejects(a.click([1, 2]), /Coordinate guard/);
    assert.deepEqual(sent, [['dev.a', [1, 2]], ['dev.a', 3], ['dev.a', [1, 2]]]);
  } finally { await guard.close(); }
});
