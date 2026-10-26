// Click a moment (or player), press "Broadcast view", wait for the stage, capture it, then check
// Esc closes it.
import { spawn } from 'node:child_process';
import { writeFileSync, mkdtempSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [, , outDir, target, language = 'en', outName = 'stage.png'] = process.argv;
mkdirSync(outDir, { recursive: true });
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9335;
const sleep = (ms) => new Promise((r) => { setTimeout(r, ms); });
const profile = mkdtempSync(join(tmpdir(), 'edge-bc-'));
const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1366,900', 'about:blank'], { stdio: 'ignore' });

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
  if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') problems.push(`console.error: ${msg.params.args.map((a) => a.value ?? a.description).join(' ')}`);
};
const send = (method, params = {}) => new Promise((resolve) => {
  id += 1;
  pending.set(id, resolve);
  ws.send(JSON.stringify({ id, method, params }));
});
const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true })).result?.result?.value;

await send('Runtime.enable'); await send('Page.enable');
await send('Page.navigate', { url: 'http://127.0.0.1:8000/' });
for (let i = 0; i < 40 && !(await evaluate("document.querySelectorAll('#moments .chip').length > 0")); i += 1) await sleep(250);

const isPlayer = target.startsWith('player:');
let sel = '#moments .chip';
if (isPlayer) sel = '#players button.prow';
else if (target === 'recap') sel = null;
const needle = isPlayer ? target.slice(7) : target;
const report = {};
if (sel) report.clicked = await evaluate(`(() => { const c=[...document.querySelectorAll(${JSON.stringify(sel)})].find(b=>b.textContent.includes(${JSON.stringify(needle)})); if(!c) return false; c.click(); return true; })()`);
await evaluate(`document.getElementById('language').value=${JSON.stringify(language)}`);
report.stageHiddenBefore = await evaluate("document.getElementById('stage-backdrop').hidden");
await evaluate("document.getElementById('btn-broadcast').click()");
const t0 = Date.now();
for (let i = 0; i < 240; i += 1) {
  await sleep(500);
  if (await evaluate("!document.getElementById('stage-backdrop').hidden || !document.getElementById('error').hidden")) break;
}
await sleep(1200); // let the entrance animation finish
report.seconds = ((Date.now() - t0) / 1000).toFixed(1);
report.stageOpen = await evaluate("!document.getElementById('stage-backdrop').hidden");
report.audienceSet = await evaluate("document.getElementById('audience').value");
report.error = await evaluate("document.getElementById('error').hidden ? null : document.getElementById('error').textContent");
report.stage = await evaluate(`(() => { const q = (s) => document.querySelector(s)?.textContent;
  return { tag: q('.lower-tag'), title: q('.lower-title'), line: q('.lower-line'), bug: q('#bug'),
    chips: [...document.querySelectorAll('.lower-chip')].map(c => c.textContent), prob: q('.prob-bar'), verified: q('.lower-verified'),
    overflowTitle: document.querySelector('.lower-title').scrollWidth > document.querySelector('.lower-title').clientWidth + 1 }; })()`);
const box = await evaluate("(() => { const r = document.getElementById('stage').getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; })()");
report.box = box;
if (box && box.width > 0) {
  const shot = await send('Page.captureScreenshot', { format: 'png', clip: { ...box, scale: 1 } });
  if (shot.result) writeFileSync(join(outDir, outName), Buffer.from(shot.result.data, 'base64'));
  else report.screenshotError = JSON.stringify(shot.error);
}
await send('Input.dispatchKeyEvent', {
  type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27,
});
await send('Input.dispatchKeyEvent', {
  type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27,
});
await sleep(300);
report.closedByEsc = await evaluate("document.getElementById('stage-backdrop').hidden");
report.consoleProblems = problems;
console.log(JSON.stringify(report, null, 1));
ws.close(); edge.kill(); process.exit(0);
