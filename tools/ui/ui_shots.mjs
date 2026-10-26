// README/submission screenshots (recorded demo): selection card, explanation and the full player
// table, in dark and light.
import { spawn } from 'node:child_process';
import { writeFileSync, mkdtempSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [, , outDir] = process.argv;
mkdirSync(outDir, { recursive: true });
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9343;
const sleep = (ms) => new Promise((r) => { setTimeout(r, ms); });
const profile = mkdtempSync(join(tmpdir(), 'edge-sh-'));
const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1500,950', 'about:blank'], { stdio: 'ignore' });

async function targetWs() {
  for (let i = 0; i < 40; i += 1) {
    try {
      const page = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch (_) { /* starting */ }
    await sleep(250);
  }
  throw new Error('no devtools');
}
const ws = new WebSocket(await targetWs());
await new Promise((r) => { ws.onopen = r; });
let id = 0; const pending = new Map(); const problems = [];
ws.onmessage = (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  if (msg.method === 'Runtime.exceptionThrown') problems.push(`EXCEPTION: ${msg.params.exceptionDetails.exception?.description}`);
};
const send = (method, params = {}) => new Promise((resolve) => {
  id += 1;
  pending.set(id, resolve);
  ws.send(JSON.stringify({ id, method, params }));
});
const ev = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true })).result?.result?.value;

await send('Runtime.enable'); await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', {
  width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
});
await send('Page.navigate', { url: 'http://127.0.0.1:8000/' });
for (let i = 0; i < 60 && !(await ev("document.querySelectorAll('#moments .chip').length > 0")); i += 1) await sleep(250);
await sleep(600);

const jpg = async (name, clip) => {
  const s = await send('Page.captureScreenshot', {
    format: 'jpeg',
    quality: 88,
    ...(clip ? { clip: { ...clip, scale: 1 }, captureBeyondViewport: true } : {}),
  });
  writeFileSync(join(outDir, name), Buffer.from(s.result.data, 'base64'));
};
const rectOf = (sel) => ev(`(() => { const r = document.querySelector(${JSON.stringify(sel)}).parentElement.getBoundingClientRect();
  return { x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height }; })()`);
const setTheme = async (t) => {
  if ((await ev("document.documentElement.dataset.theme || 'dark'")) !== t) await ev("document.getElementById('btn-theme').click()");
  await sleep(300);
};
const clickChip = (text) => ev(`[...document.querySelectorAll('#moments .chip')].find(c => c.textContent.includes(${JSON.stringify(text)})).click()`);

await setTheme('dark');
await clickChip('Goal');
await sleep(500); await jpg('select-a-moment.jpg');
await ev("document.getElementById('players').scrollIntoView()"); await sleep(300);
await jpg('all-players-dark.jpg', await rectOf('#players'));
await setTheme('light');
await jpg('all-players-light.jpg', await rectOf('#players'));
await ev('window.scrollTo(0, 0)');
await clickChip('Red card');
await ev("document.getElementById('btn-explain').click()");
for (let i = 0; i < 80 && !(await ev("!!document.querySelector('#result .verify')")); i += 1) await sleep(250);
await sleep(500); await ev('document.querySelector(\'#result .verify\').scrollIntoView({ block: "end" })'); await sleep(300);
await jpg('explanation-light.jpg');
console.log(JSON.stringify({ problems }));
ws.close(); edge.kill(); process.exit(0);
