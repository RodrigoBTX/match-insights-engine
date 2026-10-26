// Exercises the selection card, prev/next, arrow keys, clickable control cells and players in a
// real browser.
import { spawn } from 'node:child_process';
import { writeFileSync, mkdtempSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [, , outDir] = process.argv;
mkdirSync(outDir, { recursive: true });
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9338;
const sleep = (ms) => new Promise((r) => { setTimeout(r, ms); });
const profile = mkdtempSync(join(tmpdir(), 'edge-sel-'));
const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1500,900', 'about:blank'], { stdio: 'ignore' });

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
const ev = async (expression) => (await send('Runtime.evaluate', { expression, returnByValue: true })).result?.result?.value;
const key = async (k, code, vk) => {
  for (const type of ['keyDown', 'keyUp']) {
    await send('Input.dispatchKeyEvent', {
      type, key: k, code, windowsVirtualKeyCode: vk,
    });
  } await sleep(250);
};
async function shot(name, selector) {
  let params = { format: 'png' };
  if (selector) {
    const box = await ev(`(() => { const r = document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect(); return { x: r.x + window.scrollX, y: r.y + window.scrollY, width: r.width, height: r.height }; })()`);
    params = { ...params, clip: { ...box, scale: 1 } };
  }
  const s = await send('Page.captureScreenshot', params);
  if (s.result) writeFileSync(join(outDir, name), Buffer.from(s.result.data, 'base64'));
}
const info = () => ev(`(() => { const b = document.getElementById('info'); const q = (s) => b.querySelector(s)?.textContent;
  return { tag: q('.info-tag'), head: q('.info-head b'), title: q('.info-title'), sub: q('.info-sub'), pos: q('.info-pos'),
    chips: [...b.querySelectorAll('.statchip')].map(c => [...c.children].map(x => x.textContent).join(' | ')),
    mini: b.querySelector('.mini-pitch') ? b.querySelector('.mini-pitch').querySelectorAll('*').length : 0,
    opens: [...b.querySelectorAll('.info-open')].map(x => x.textContent), hint: q('.info-hint') }; })()`);

await send('Runtime.enable'); await send('Page.enable');
await send('Page.navigate', { url: 'http://127.0.0.1:8000/' });
for (let i = 0; i < 60 && !(await ev("document.querySelectorAll('#momentum .marker').length > 0 && document.querySelectorAll('#control .cell').length > 0")); i += 1) await sleep(250);
await sleep(800);

const R = {};
R.initial = await info();
R.markers = await ev("document.querySelectorAll('#momentum .marker').length");
R.cells = await ev("document.querySelectorAll('#control .cell').length");

// 1. a marker, clicked while the momentum card is what the user is looking at
await ev("document.getElementById('momentum').scrollIntoView({block: 'center'})");
await sleep(300);
R.clickMs = await ev(`(() => { const el = document.querySelectorAll('#momentum .marker')[6]; const t = performance.now();
  el.dispatchEvent(new MouseEvent('click', { bubbles: true })); return +(performance.now() - t).toFixed(1); })()`);
R.afterMarker = await info();
R.panelVisibleWhileMomentumInView = await ev(`(() => { const p = document.querySelector('.panel').getBoundingClientRect(); const m = document.getElementById('momentum').getBoundingClientRect();
  return { panelTop: Math.round(p.top), panelBottom: Math.round(p.bottom), viewport: innerHeight, momentumTop: Math.round(m.top), momentumBottom: Math.round(m.bottom) }; })()`);
await shot('sel_1_marker_viewport.png');

// 2. next / previous with wrap-around, and the arrow keys
const posOf = async () => (await info()).pos;
R.nav = { start: await posOf() };
await ev("document.getElementById('next-moment').click()"); R.nav.afterNext = await posOf();
await key('ArrowRight', 'ArrowRight', 39); R.nav.afterArrowRight = await posOf();
await key('ArrowLeft', 'ArrowLeft', 37); await key('ArrowLeft', 'ArrowLeft', 37); R.nav.afterTwoArrowLeft = await posOf();
// wrap: from the last to the first, and from the first back to the last
await ev("(() => { const n = document.querySelectorAll('#momentum .marker').length; document.querySelectorAll('#momentum .marker')[n - 1].dispatchEvent(new MouseEvent('click', { bubbles: true })); })()");
R.nav.atLast = await posOf();
await ev("document.getElementById('next-moment').click()"); R.nav.wrappedToFirst = await posOf();
await ev("document.getElementById('prev-moment').click()"); R.nav.wrappedBackToLast = await posOf();

// 3. cost of repeated selection changes
R.stepAvgMs = await ev("(() => { const t = performance.now(); for (let i = 0; i < 20; i += 1) document.getElementById('next-moment').click(); return +((performance.now() - t) / 20).toFixed(1); })()");

// 4. control cells: a chaotic window, then the moment it offers to open
await ev("document.getElementById('control').scrollIntoView({block: 'center'})");
const chaoticIdx = await ev("[...document.querySelectorAll('#control .cell')].findIndex(c => c.getAttribute('aria-label').includes('Chaotic'))");
R.chaoticCell = chaoticIdx;
await ev(`document.querySelectorAll('#control .cell')[${chaoticIdx}].dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
R.afterCell = await info();
await shot('sel_2_window_viewport.png');
R.cellPressed = await ev('document.querySelectorAll(\'#control .cell[aria-pressed="true"]\').length');
await ev("document.querySelector('.info-open')?.click()");
R.afterOpen = await info();
// same window clicked twice deselects
await ev("document.querySelectorAll('#control .cell')[0].dispatchEvent(new MouseEvent('click', { bubbles: true }))");
R.firstCell = await info();
await ev("document.querySelectorAll('#control .cell')[0].dispatchEvent(new MouseEvent('click', { bubbles: true }))");
R.deselected = (await info()).hint ? 'hint shown again' : 'still selected';

// 5. players: an outfielder and the goalkeeper
for (const [needle, name] of [['Idris Moreau', 'outfield'], ['Viktor Rask', 'keeper']]) {
  await ev(`[...document.querySelectorAll('#players button.prow')].find(b => b.textContent.includes(${JSON.stringify(needle)})).click()`);
  R[name] = await info();
}
await shot('sel_3_player_viewport.png');

// 6. the explain flow still works and a long result scrolls inside the panel instead of being cut
// off
await ev("[...document.querySelectorAll('#moments .chip')].find(c => c.textContent.includes('Red card')).click()");
await ev("document.getElementById('btn-explain').click()");
for (let i = 0; i < 40 && await ev("document.getElementById('result').hidden"); i += 1) await sleep(250);
R.explain = await ev(`(() => { const p = document.querySelector('.panel'); const r = document.getElementById('result');
  return { resultShown: !r.hidden, h3: r.querySelector('h3')?.textContent, panelScrollable: p.scrollHeight > p.clientHeight, panelClient: p.clientHeight, panelScroll: p.scrollHeight, overflowY: getComputedStyle(p).overflowY }; })()`);
await ev("document.querySelector('.panel').scrollTo(0, 99999)");
await sleep(200);
R.panelBottomReachable = await ev("(() => { const p = document.querySelector('.panel'); return Math.abs(p.scrollTop + p.clientHeight - p.scrollHeight) < 3; })()");
await shot('sel_4_after_explain_viewport.png');

R.consoleProblems = problems;
console.log(JSON.stringify(R, null, 1));
ws.close(); edge.kill(); process.exit(0);
