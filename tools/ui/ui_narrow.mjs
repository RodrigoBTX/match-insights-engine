// Narrow screens: horizontal overflow and tap-target size at phone and tablet widths, light and
// dark, with screenshots.
import { spawn } from 'node:child_process';
import { writeFileSync, mkdtempSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [, , outDir] = process.argv;
mkdirSync(outDir, { recursive: true });
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9345;
const sleep = (ms) => new Promise((r) => { setTimeout(r, ms); });
const profile = mkdtempSync(join(tmpdir(), 'edge-nr-'));
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
const jpg = async (name, full) => {
  const s = await send('Page.captureScreenshot', { format: 'jpeg', quality: 80, captureBeyondViewport: !!full });
  writeFileSync(join(outDir, name), Buffer.from(s.result.data, 'base64'));
};

const OVERFLOW = `(() => {
  const vw = document.documentElement.clientWidth, wide = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (r.width && r.right > vw + 1 && !el.closest('svg') && !el.closest('[hidden]') && getComputedStyle(el).position !== 'fixed') wide.push(el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + '.' + String(el.className).split(' ')[0] + ' right=' + Math.round(r.right));
  }
  const small = [...document.querySelectorAll('button, select, a, [role=button]')].filter((e) => { const r = e.getBoundingClientRect(); return r.width && (r.height < 32) && !e.closest('[hidden]') && !e.closest('svg'); }).length;
  return { scrollWidth: document.documentElement.scrollWidth, vw, overflowing: wide.slice(0, 8), controlsUnder32px: small };
})()`;

await send('Runtime.enable'); await send('Page.enable');
const R = {};
for (const [name, width, height] of [['phone', 390, 844], ['tablet', 820, 1180]]) {
  await send('Emulation.setDeviceMetricsOverride', {
    width, height, deviceScaleFactor: 1, mobile: true,
  });
  await send('Page.navigate', { url: 'http://127.0.0.1:8000/' });
  for (let i = 0; i < 60 && !(await ev("document.querySelectorAll('#moments .chip').length > 0")); i += 1) await sleep(250);
  await sleep(700);
  R[name] = { top: await ev(OVERFLOW) };
  await jpg(`${name}_top.jpg`);
  await ev("[...document.querySelectorAll('#moments .chip')].find(c => c.textContent.includes('Red card')).click()"); await sleep(500);
  R[name].selected = await ev(OVERFLOW);
  await ev("document.getElementById('btn-explain').click()");
  for (let i = 0; i < 40 && !(await ev("!!document.querySelector('#result .verify')")); i += 1) await sleep(250);
  await sleep(400);
  R[name].result = await ev(OVERFLOW);
  await jpg(`${name}_full.jpg`, true);
  await ev("document.getElementById('btn-theme').click()"); await sleep(300);
  await jpg(`${name}_light_full.jpg`, true);
  await ev("document.getElementById('btn-theme').click()");
  await ev("document.getElementById('btn-broadcast').click()");
  for (let i = 0; i < 40 && (await ev("document.getElementById('stage-backdrop').hidden")); i += 1) await sleep(250);
  await sleep(500);
  R[name].stage = await ev("(() => { const s = document.querySelector('#stage-backdrop .stage'); const r = s && s.getBoundingClientRect(); return r ? { w: Math.round(r.width), right: Math.round(r.right), vw: document.documentElement.clientWidth } : null; })()");
  await jpg(`${name}_stage.jpg`);
  await ev("document.getElementById('stage-close').click()");
}
R.consoleProblems = problems;
console.log(JSON.stringify(R, null, 1));
ws.close(); edge.kill(); process.exit(0);
