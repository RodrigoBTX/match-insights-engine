// Uploads real-feed fixtures through the page's file input and reports what the UI shows.
import { spawn } from 'node:child_process';
import { writeFileSync, mkdtempSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [, , outDir, ...files] = process.argv;
mkdirSync(outDir, { recursive: true });
const EDGE = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const PORT = 9334;
const sleep = (ms) => new Promise((r) => { setTimeout(r, ms); });
const profile = mkdtempSync(join(tmpdir(), 'edge-up-'));
const edge = spawn(EDGE, ['--headless=new', '--disable-gpu', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--window-size=1440,1400', 'about:blank'], { stdio: 'ignore' });

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

await send('Runtime.enable'); await send('Page.enable'); await send('DOM.enable');
await send('Page.navigate', { url: 'http://127.0.0.1:8000/' });
for (let i = 0; i < 40 && !(await evaluate("document.querySelectorAll('#moments .chip').length > 0")); i += 1) await sleep(250);

const reports = [];
for (const [n, file] of files.entries()) {
  const doc = (await send('DOM.getDocument')).result.root.nodeId;
  const node = (await send('DOM.querySelector', { nodeId: doc, selector: '#file' })).result.nodeId;
  const before = await evaluate("document.getElementById('source').textContent");
  await send('DOM.setFileInputFiles', { files: [file], nodeId: node });
  for (let i = 0; i < 40 && (await evaluate("document.getElementById('source').textContent")) === before; i += 1) await sleep(250);
  await sleep(500);
  reports.push({
    file: file.split('\\').pop(),
    source: await evaluate("document.getElementById('source').textContent"),
    score: await evaluate("document.querySelector('#scoreboard .score')?.textContent"),
    teams: await evaluate("[...document.querySelectorAll('#scoreboard .team-name')].map(e => e.textContent).join(' vs ')"),
    moments: await evaluate("document.querySelectorAll('#moments .chip').length"),
    playerRows: await evaluate("document.querySelectorAll('#players button.prow').length"),
    firstPlayer: await evaluate("document.querySelector('#players button.prow .pname')?.textContent"),
    controlCells: await evaluate("document.querySelectorAll('#control rect').length"),
    error: await evaluate("document.getElementById('error').hidden ? null : document.getElementById('error').textContent"),
  });
  const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
  writeFileSync(join(outDir, `upload_${n}.png`), Buffer.from(shot.result.data, 'base64'));
}
console.log(JSON.stringify({ reports, consoleProblems: problems }, null, 1));
ws.close(); edge.kill(); process.exit(0);
