// Visual audit: screenshots every chart/graphic state of the app (server must run with DEMO_ONLY=1
// for instant results).
import { spawn } from 'node:child_process';
import { writeFileSync, mkdtempSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [, , outDir] = process.argv;
mkdirSync(outDir, { recursive: true });
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9337;
const sleep = (ms) => new Promise((r) => { setTimeout(r, ms); });
const profile = mkdtempSync(join(tmpdir(), 'edge-au-'));
const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1366,1000', 'about:blank'], { stdio: 'ignore' });

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
async function waitFor(cond, ms = 20000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (await ev(cond)) return true; await sleep(150); }
  return false;
}
async function shotOf(selector, name, pad = 0) {
  const box = await ev(`(() => { const e = document.querySelector(${JSON.stringify(selector)}); if (!e) return null;
    e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect();
    return { x: r.x + window.scrollX - ${pad}, y: r.y + window.scrollY - ${pad}, width: r.width + ${pad * 2}, height: r.height + ${pad * 2} }; })()`);
  if (!box || box.width <= 0) return false;
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { ...box, scale: 1 } });
  if (!shot.result) return false;
  writeFileSync(join(outDir, name), Buffer.from(shot.result.data, 'base64'));
  return true;
}

await send('Runtime.enable'); await send('Page.enable');
await send('Page.navigate', { url: 'http://127.0.0.1:8000/' });
await waitFor("document.querySelectorAll('#moments .chip').length > 0 && document.querySelectorAll('#players button.prow').length > 0");
await sleep(1200);

const report = { files: [], missing: [] };
const log = (ok, name) => (ok ? report.files : report.missing).push(name);

// whole page and the individual cards
log(await shotOf('body', '00_page.png'), '00_page.png');
await ev('window.scrollTo(0, 0)');
for (const [sel, name] of [['#scoreboard', '01_scoreboard.png'], ['#momentum', '02_momentum.png'], ['#control', '03_control.png'],
  ['#players', '04_players.png'], ['#xg', '05_xg.png'], ['#poss', '06_possession.png']]) {
  const parent = `${sel}`;
  log(await shotOf(parent === '#players' || parent === '#scoreboard' ? parent : `${parent}`, name, 0), name);
}
// card-level shots (title + chart + note) for the charts
for (const [sel, name] of [['#momentum', '02c_momentum_card.png'], ['#control', '03c_control_card.png'], ['#xg', '05c_xg_card.png'], ['#poss', '06c_poss_card.png']]) {
  const ok = await (async () => {
    const box = await ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}).closest('.card'); e.scrollIntoView({block:'center'}); const r = e.getBoundingClientRect(); return { x: r.x + window.scrollX, y: r.y + window.scrollY, width: r.width, height: r.height }; })()`);
    const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { ...box, scale: 1 } });
    if (!shot.result) return false;
    writeFileSync(join(outDir, name), Buffer.from(shot.result.data, 'base64')); return true;
  })();
  log(ok, name);
}

// one pitch replay per moment
const moments = await ev("[...document.querySelectorAll('#moments .chip')].map(c => c.textContent)");
report.moments = moments;
for (let i = 0; i < moments.length; i += 1) {
  await ev(`document.querySelectorAll('#moments .chip')[${i}].click()`);
  await sleep(2200); // let the replay animation finish
  const name = `10_pitch_m${String(i + 1).padStart(2, '0')}.png`;
  const box = await ev("(() => { const e = document.getElementById('pitch').closest('.card'); e.scrollIntoView({block:'start'}); const r = e.getBoundingClientRect(); return { x: r.x + window.scrollX, y: r.y + window.scrollY, width: r.width, height: r.height }; })()");
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { ...box, scale: 1 } });
  if (shot.result) { writeFileSync(join(outDir, name), Buffer.from(shot.result.data, 'base64')); report.files.push(name); } else report.missing.push(name);
}

// broadcast graphic per moment, in the audience the demo records (broadcaster, English)
async function stage(clickJs, name) {
  await ev(clickJs);
  await ev("(() => { document.getElementById('language').value='en'; })()");
  await ev("document.getElementById('btn-broadcast').click()");
  await waitFor("!document.getElementById('stage-backdrop').hidden || !document.getElementById('error').hidden", 15000);
  await sleep(1300);
  const info = await ev(`(() => { const q=(s)=>document.querySelector(s)?.textContent; return { open: !document.getElementById('stage-backdrop').hidden, tag: q('.lower-tag'), title: q('.lower-title'), line: q('.lower-line'),
    chips: [...document.querySelectorAll('.lower-chip')].map(c => [...c.children].map(x => x.textContent).join(' | ')), error: document.getElementById('error').hidden ? null : document.getElementById('error').textContent }; })()`);
  report[name] = info;
  if (info.open) {
    // clip coordinates are page coordinates, so the scroll offset must be added
    const box = await ev("(() => { const r = document.getElementById('stage').getBoundingClientRect(); return { x: r.x + window.scrollX, y: r.y + window.scrollY, width: r.width, height: r.height }; })()");
    const shot = await send('Page.captureScreenshot', { format: 'png', clip: { ...box, scale: 1 } });
    if (shot.result) writeFileSync(join(outDir, `${name}.png`), Buffer.from(shot.result.data, 'base64'));
    await ev("document.getElementById('stage-close').click()");
    await sleep(250);
  }
}
for (let i = 0; i < moments.length; i += 1) {
  await stage(`document.querySelectorAll('#moments .chip')[${i}].click()`, `20_stage_m${String(i + 1).padStart(2, '0')}`);
}
// recap: deselect everything first
await ev('(() => { const sel = document.querySelector(\'#moments .chip[aria-pressed="true"]\'); if (sel) sel.click(); })()');
await stage('1', '21_stage_recap');
// players: first row of each team and a goalkeeper
for (const [needle, name] of [['Idris Moreau', '22_stage_player_home'], ['Anders Voll', '22_stage_player_away'], ['Viktor Rask', '22_stage_player_gk']]) {
  await stage(`(() => { const c=[...document.querySelectorAll('#players button.prow')].find(b => b.textContent.includes(${JSON.stringify(needle)})); if (c) c.click(); })()`, name);
}

report.consoleProblems = problems;
console.log(JSON.stringify(report, null, 1));
ws.close(); edge.kill(); process.exit(0);
