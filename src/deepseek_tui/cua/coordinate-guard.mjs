// Host-only window geometry stream. The runtime can read files but cannot write or use TCP.
import { mkdtemp, writeFile, rename, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
const execute = promisify(execFile);

export async function createCoordinateGuard(script, readWindows = async () => {
  const { stdout } = await execute('/usr/bin/osascript', ['-l', 'JavaScript', '-e', script],
    { timeout: 3000, maxBuffer: 1024 * 1024 });
  return JSON.parse(stdout);
}) {
  const directory = await mkdtemp(join(tmpdir(), 'deepseek-cua-geometry-'));
  const path = join(directory, 'windows.json');
  let running = false, task;
  async function sample() {
    while (running) {
      const started = Date.now();
      let frames = {};
      try { frames = await readWindows(); } catch { /* Unknown geometry fails closed. */ }
      await writeFile(path + '.tmp', JSON.stringify({ started, frames }), { mode: 0o600 });
      await rename(path + '.tmp', path);
      if (running) await new Promise(resolve => setTimeout(resolve, 20));
    }
  }
  return {
    path,
    start() { if (!running) { running = true; task = sample(); task.catch(() => { running = false; }); } },
    async stop() { running = false; await task?.catch(() => {}); },
    async close() { await this.stop(); await rm(directory, { recursive: true, force: true }); }
  };
}
