import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const modulePath = process.env.PLAYWRIGHT_MODULE_PATH;
const { chromium } = require(modulePath ? join(modulePath, 'index.js') : 'playwright-core');
const version = require(modulePath ? join(modulePath, 'package.json') : 'playwright-core/package.json').version;
assert.equal(version, '1.58.2', 'Use the pinned Playwright version.');
const here = dirname(fileURLToPath(import.meta.url));
const reason = error => error.message.split('\n')[0];
const timeout = value => {
  const ms = value ?? 1500;
  if (!Number.isInteger(ms) || ms < 1 || ms > 3000) throw new Error('timeout must be 1..3000 ms');
  return ms;
};
const localURL = url => {
  const parsed = new URL(url);
  if (parsed.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(parsed.hostname)) {
    throw new Error('This demo accepts only HTTP loopback pages.');
  }
  return parsed.href;
};

export class BrowserSession {
  constructor(context, profile) {
    this.context = context;
    this.profile = profile;
    this.sessionId = randomUUID();
    this.tabs = new Map();
    this.generation = 0;
    this.paused = false;
  }

  static async launch() {
    const profile = await mkdtemp(join(tmpdir(), 'browser-use-demo-'));
    try {
      const context = await chromium.launchPersistentContext(profile, {
        executablePath: process.env.CHROME_EXECUTABLE_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
        headless: true, viewport: { width: 1100, height: 1000 },
      });
      await context.route('**/*', route => {
        try { localURL(route.request().url()); return route.continue(); }
        catch { return route.abort(); }
      });
      return new BrowserSession(context, profile);
    } catch (error) {
      await rm(profile, { recursive: true, force: true });
      throw error;
    }
  }

  get page() {
    const page = this.tabs.get(this.tabId);
    if (!page || page.isClosed()) throw new Error('No active owned tab.');
    return page;
  }

  invalidate() { this.generation++; this.lastToken = null; }

  async openTab(url) {
    url = localURL(url);
    const page = await this.context.newPage();
    const tabId = randomUUID();
    this.tabs.set(tabId, page);
    page.on('framenavigated', () => this.invalidate());
    await page.goto(url, { waitUntil: 'load', timeout: 3000 });
    this.tabId = tabId;
    this.invalidate();
    return this.observe();
  }

  async switchTab(tabId) {
    if (!this.tabs.has(tabId)) throw new Error('Unknown tab.');
    this.tabId = tabId;
    this.invalidate();
    return this.observe();
  }

  takeover(paused = true) {
    this.paused = paused;
    this.invalidate();
    return { paused, generation: this.generation };
  }

  async observe() {
    if (this.failNextObservation) {
      this.failNextObservation = false;
      throw new Error('Injected observation failure for the demo.');
    }
    const generation = this.generation;
    const page = this.page;
    const frames = [];
    for (const frame of page.frames()) {
      const tree = await frame.locator('body').ariaSnapshot({ timeout: 1500 });
      frames.push({ url: frame.url(), name: frame.name(), tree: tree.slice(0, 16000), truncated: tree.length > 16000 });
    }
    if (generation !== this.generation || page !== this.page) throw new Error('Page changed during observation; observe again.');
    this.lastToken = randomUUID();
    return { sessionId: this.sessionId, tabId: this.tabId, generation, token: this.lastToken, url: page.url(), frames };
  }

  async root(spec = {}) {
    let root = this.page;
    if (spec.frame) {
      const frame = root.getByTitle(spec.frame, { exact: true }).filter({ visible: true });
      if (await frame.count() !== 1) throw new Error('Frame title must identify exactly one visible iframe.');
      root = frame.contentFrame();
    }
    if (spec.scope) {
      root = root.getByRole(spec.scope.role, { name: spec.scope.name, exact: true }).filter({ visible: true });
      if (await root.count() !== 1) throw new Error('Scope must identify exactly one visible element.');
    }
    return root;
  }

  async target(spec) {
    if (!spec?.role || typeof spec.name !== 'string') throw new Error('A semantic role and exact name are required.');
    const root = await this.root(spec);
    const locator = root.getByRole(spec.role, { name: spec.name, exact: true }).filter({ visible: true });
    const count = await locator.count();
    if (count !== 1) throw new Error(`Target must be unique and visible; matched ${count}.`);
    return locator;
  }

  async waitFor(condition) {
    if (typeof condition.text !== 'string') throw new Error('An exact effect text is required.');
    const root = await this.root(condition);
    await root.getByText(condition.text, { exact: true }).filter({ visible: true }).waitFor({ state: 'visible', timeout: timeout(condition.timeout) });
    return { state: 'verified', text: condition.text };
  }

  checkObservation(observation) {
    if (this.paused) throw new Error('Human takeover is active.');
    if (observation?.sessionId !== this.sessionId || observation.tabId !== this.tabId ||
        observation.generation !== this.generation || observation.token !== this.lastToken || !this.lastToken) {
      throw new Error('Stale observation or wrong session/tab; observe again.');
    }
  }

  async act({ observation, action, target, value, effect }) {
    let locator;
    try {
      this.checkObservation(observation);
      if (!['click', 'fill'].includes(action)) throw new Error('Supported actions: click, fill.');
      locator = await this.target(target);
      if (action === 'click') await locator.click({ trial: true, timeout: 750 });
      else if (typeof value !== 'string' || !await locator.isEditable()) throw new Error('Fill needs an editable target and string value.');
      if (effect) timeout(effect.timeout);
      this.checkObservation(observation);
    } catch (error) {
      return { execution: { state: 'rejected', reason: reason(error) }, effect: null, observation: null };
    }
    this.invalidate();
    let execution, result = null;
    try {
      if (action === 'click') await locator.click({ timeout: 1000 });
      else await locator.fill(value, { timeout: 1000 });
      execution = { state: 'completed' };
    } catch (error) { execution = { state: 'unknown', reason: reason(error) }; }
    if (execution.state === 'completed' && effect) {
      try { result = await this.waitFor(effect); }
      catch (error) { result = { state: 'unverified', reason: reason(error) }; }
    }
    try { return { execution, effect: result, observation: await this.observe() }; }
    catch (error) { return { execution, effect: result, observation: null, requiresObserve: true, observationError: reason(error) }; }
  }

  async close() {
    try { await this.context.close(); }
    finally { await rm(this.profile, { recursive: true, force: true }); }
  }
}

async function demo() {
  const fixtures = new Map(await Promise.all(['demo.html', 'frame.html'].map(async name => [name, await readFile(join(here, '..', name))])));
  const server = createServer((req, res) => {
    const content = fixtures.get(new URL(req.url, 'http://localhost').pathname.slice(1));
    res.writeHead(content ? 200 : 404, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end(content || 'Not found');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let session;
  const checks = [], trace = [];
  const check = (name, actual) => { assert.ok(actual, name); checks.push({ name, passed: true }); };
  const results = join(here, 'results');
  await mkdir(results, { recursive: true });
  try {
    session = await BrowserSession.launch();
    const url = `http://localhost:${server.address().port}/demo.html`;
    let observation = await session.openTab(url);
    const firstTab = observation.tabId;
    await session.page.screenshot({ path: join(results, 'before.png'), fullPage: true });
    const region = name => ({ role: 'region', name });
    const button = (name, scope) => ({ role: 'button', name, ...(scope && { scope: region(scope) }) });
    const run = async (action, target, value, effect) => {
      const output = await session.act({ observation, action, target, value, effect });
      trace.push({ action, target, value, requestedEffect: effect, ...output });
      if (output.observation) observation = output.observation;
      return output;
    };
    await run('fill', { role: 'textbox', name: '项目名称', scope: region('本地表单') }, '复现项目');
    let out = await run('click', button('保存项目', '本地表单'), undefined, { text: '已保存：复现项目', scope: region('本地表单') });
    check('语义填写、提交与条件等待；保存恰好一次', out.execution.state === 'completed' && out.effect.state === 'verified' && await session.page.getByText('保存次数：1', { exact: true }).count() === 1);
    out = await run('click', button('延迟显示结果'), undefined, { text: '延迟结果已出现' });
    check('有限条件等待', out.effect.state === 'verified');
    out = await run('click', button('重复按钮'));
    check('重复目标明确拒绝', out.execution.state === 'rejected' && out.execution.reason.includes('matched 2'));
    out = await run('click', button('可见按钮'), undefined, { text: '唯一可见目标已点击' });
    check('仅隐藏重复项时选择唯一可见目标', out.effect.state === 'verified');
    out = await run('click', button('被遮挡按钮'));
    check('遮挡点击在执行前拒绝且无副作用', out.execution.state === 'rejected' && await session.page.getByText('尚未点击', { exact: true }).count() === 1);
    await run('click', button('移除遮挡层'));
    out = await run('click', button('被遮挡按钮'), undefined, { text: '遮挡目标已点击' });
    check('解除遮挡后可执行', out.effect.state === 'verified');
    const frame = '跨源验证表单';
    await run('fill', { role: 'textbox', name: 'Frame 名称', frame }, '跨源项目');
    out = await run('click', { ...button('Frame 保存'), frame }, undefined, { text: 'Frame 已保存：跨源项目', frame });
    check('跨源 frame 独立定位与验证', out.effect.state === 'verified' && new URL(out.observation.frames[1].url).origin !== new URL(url).origin);
    out = await run('click', button('Shadow 保存'), undefined, { text: 'Shadow 已保存' });
    check('开放 Shadow DOM 语义操作', out.effect.state === 'verified');
    const stale = observation;
    await session.observe();
    out = await session.act({ observation: stale, action: 'click', target: button('保存项目') });
    trace.push({ scenario: 'stale observation', ...out });
    check('新观察使旧观察失效', out.execution.state === 'rejected');
    observation = await session.observe();
    const preTakeover = observation;
    session.takeover();
    out = await run('click', button('保存项目'));
    check('接管期间拒绝执行', out.execution.reason === 'Human takeover is active.');
    session.takeover(false);
    out = await session.act({ observation: preTakeover, action: 'click', target: button('保存项目') });
    trace.push({ scenario: 'after takeover', ...out });
    check('恢复后必须重新观察', out.execution.state === 'rejected');
    observation = await session.observe();
    const originalTarget = session.target;
    session.target = async function (spec) {
      const locator = await originalTarget.call(this, spec);
      this.takeover();
      return locator;
    };
    try { out = await run('click', button('保存项目')); }
    finally { session.target = originalTarget; session.takeover(false); }
    check('预检查期间接管：派发前重新校验并拒绝', out.execution.state === 'rejected' && out.execution.reason === 'Human takeover is active.' && await session.page.getByText('保存次数：1', { exact: true }).count() === 1);
    observation = await session.observe();
    await session.page.screenshot({ path: join(results, 'verified.png'), fullPage: true });
    const firstObservation = observation;
    observation = await session.openTab(url);
    const secondTab = observation.tabId;
    out = await session.act({ observation: firstObservation, action: 'fill', target: { role: 'textbox', name: '项目名称' }, value: '错误标签页' });
    trace.push({ scenario: 'wrong tab', ...out });
    check('跨标签页 token 明确拒绝', out.execution.state === 'rejected' && await session.page.getByRole('textbox', { name: '项目名称' }).inputValue() === '');
    observation = await session.switchTab(firstTab);
    check('切换后绑定原标签页状态', await session.page.getByRole('textbox', { name: '项目名称' }).inputValue() === '复现项目' && observation.token !== firstObservation.token);
    observation = await session.switchTab(secondTab);
    session.target = async function (spec) {
      const locator = await originalTarget.call(this, spec);
      await this.page.reload({ waitUntil: 'load', timeout: 3000 });
      return locator;
    };
    try { out = await run('click', button('保存项目')); }
    finally { session.target = originalTarget; }
    check('预检查期间导航：派发前拒绝旧观察', out.execution.state === 'rejected' && out.execution.reason.startsWith('Stale observation') && await session.page.getByText('保存次数：0', { exact: true }).count() === 1);
    observation = await session.observe();
    await run('fill', { role: 'textbox', name: '项目名称' }, '只执行一次');
    const beforeSubmit = observation;
    session.failNextObservation = true;
    out = await run('click', button('保存项目'), undefined, { text: '已保存：只执行一次' });
    check('动作完成、观察失败仍保留执行事实', out.execution.state === 'completed' && out.effect.state === 'verified' && out.requiresObserve && !out.observation);
    out = await session.act({ observation: beforeSubmit, action: 'click', target: button('保存项目') });
    trace.push({ scenario: 'prevent replay after observation failure', ...out });
    observation = await session.observe();
    check('观察失败后不重放；再次观察确认一次', out.execution.state === 'rejected' && await session.page.getByText('保存次数：1', { exact: true }).count() === 1);
    out = await run('click', button('延迟显示结果'), undefined, { text: '不会出现的结果', timeout: 100 });
    check('效果等待超时与动作完成分开记录', out.execution.state === 'completed' && out.effect.state === 'unverified' && !!out.observation);
    await session.page.screenshot({ path: join(results, 'after.png'), fullPage: true });
    await writeFile(join(results, 'report.json'), JSON.stringify({ generatedAt: new Date().toISOString(), playwright: version, checks, trace, finalObservation: observation }, null, 2));
    process.stdout.write(JSON.stringify({ passed: checks.length, total: checks.length, results }) + '\n');
  } finally {
    try { if (session) await session.close(); }
    finally { await new Promise(resolve => server.close(resolve)); }
  }
}

async function protocol() {
  const session = await BrowserSession.launch();
  const input = createInterface({ input: process.stdin, crlfDelay: Infinity });
  try {
    for await (const line of input) {
      if (!line.trim()) continue;
      let id;
      try {
        const request = JSON.parse(line); id = request.id;
        let result;
        switch (request.op) {
          case 'open': result = await session.openTab(request.url); break;
          case 'switch': result = await session.switchTab(request.tabId); break;
          case 'observe': result = await session.observe(); break;
          case 'act': result = await session.act(request); break;
          case 'wait': result = await session.waitFor(request.condition); break;
          case 'takeover': result = session.takeover(); break;
          case 'resume': result = session.takeover(false); break;
          default: throw new Error('Unknown op.');
        }
        process.stdout.write(JSON.stringify({ id, result }) + '\n');
      } catch (error) { process.stdout.write(JSON.stringify({ id, error: reason(error) }) + '\n'); }
    }
  } finally { await session.close(); }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  (process.argv.includes('--demo') ? demo() : protocol()).catch(error => { console.error(error); process.exitCode = 1; });
}
