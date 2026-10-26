// Walks the app the way someone without Azure would: badge, recorded result, fallback, player, broadcast, new match.
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [, , outDir] = process.argv;
mkdirSync(outDir, { recursive: true });
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9336;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "edge-dm-"));
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--window-size=1366,1000", "about:blank"], { stdio: "ignore" });

async function targetWs() {
  for (let i = 0; i < 40; i++) {
    try {
      const page = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch (_) { /* starting */ }
    await sleep(250);
  }
  throw new Error("no devtools");
}
const ws = new WebSocket(await targetWs());
await new Promise((r) => (ws.onopen = r));
let id = 0; const pending = new Map(); const problems = [];
ws.onmessage = (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  if (msg.method === "Runtime.exceptionThrown") problems.push("EXCEPTION: " + msg.params.exceptionDetails.exception?.description);
  if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") problems.push("console.error: " + msg.params.args.map((a) => a.value ?? a.description).join(" "));
};
const send = (method, params = {}) => new Promise((resolve) => { const i = ++id; pending.set(i, resolve); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expression) => (await send("Runtime.evaluate", { expression, returnByValue: true })).result?.result?.value;

async function waitFor(cond, ms = 60000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (await ev(cond)) return ((Date.now() - t0) / 1000).toFixed(1); await sleep(250); }
  return "timeout";
}
const click = (sel, needle) => ev(`(() => { const c=[...document.querySelectorAll(${JSON.stringify(sel)})].find(b=>b.textContent.includes(${JSON.stringify(needle)})); if(!c) return false; c.click(); return true; })()`);
const resultInfo = () => ev(`(() => { const r=document.getElementById('result'); if (r.hidden) return null;
  return { h3: r.querySelector('h3')?.textContent, tag: r.querySelector('.tag')?.textContent, fallback: r.querySelector('.fallback-note')?.textContent,
           verify: r.querySelector('.verify b')?.textContent }; })()`);

await send("Runtime.enable"); await send("Page.enable");
await send("Page.navigate", { url: "http://127.0.0.1:8000/" });
await waitFor(`document.querySelectorAll('#moments .chip').length > 0`);
await sleep(1500);
const report = { badge: await ev(`document.getElementById('mode').textContent`), badgeTitle: await ev(`document.getElementById('mode').title`) };

// 1. recorded moment: coach / English
await click("#moments .chip", "Red card");
await ev(`(() => { document.getElementById('audience').value='coach'; document.getElementById('language').value='en'; })()`);
await ev(`document.getElementById('btn-explain').click()`);
report.recordedMomentSeconds = await waitFor(`!document.getElementById('result').hidden || !document.getElementById('error').hidden`);
report.recordedMoment = await resultInfo();
report.afterMomentBadge = await ev(`document.getElementById('mode').textContent`);

// 2. a language that is not recorded -> falls back with a notice
await ev(`document.getElementById('language').value='fr'`);
await ev(`document.getElementById('btn-explain').click()`);
report.fallbackSeconds = await waitFor(`document.querySelector('#result .fallback-note') !== null || !document.getElementById('error').hidden`);
report.fallback = await resultInfo();

// 3. a recorded player
await click("#players button.prow", "Idris Moreau");
await ev(`(() => { document.getElementById('audience').value='casual_fan'; document.getElementById('language').value='en'; })()`);
await ev(`document.getElementById('btn-explain').click()`);
await waitFor(`!document.getElementById('result').hidden && document.querySelector('#result h3')?.textContent.includes('Moreau') || !document.getElementById('error').hidden`);
report.player = await resultInfo();

// 4. broadcast view from recordings, Portuguese
await click("#moments .chip", "Goal – Northbridge FC (set-piece)");
await ev(`document.getElementById('language').value='pt'`);
await ev(`document.getElementById('btn-broadcast').click()`);
report.broadcastSeconds = await waitFor(`!document.getElementById('stage-backdrop').hidden || !document.getElementById('error').hidden`);
await sleep(1200);
report.stage = await ev(`(() => { const q=(s)=>document.querySelector(s)?.textContent; return { open: !document.getElementById('stage-backdrop').hidden, tag: q('.lower-tag'), title: q('.lower-title'), line: q('.lower-line'), verified: q('.lower-verified') }; })()`);
const box = await ev(`(() => { const r = document.getElementById('stage').getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height }; })()`);
if (box && box.width > 0) {
  const shot = await send("Page.captureScreenshot", { format: "png", clip: { ...box, scale: 1 } });
  if (shot.result) writeFileSync(join(outDir, "demo_stage.png"), Buffer.from(shot.result.data, "base64"));
}
await ev(`document.getElementById('stage-close').click()`);

// 5. a new synthetic match has no recordings and no live agents: must say so clearly
await ev(`document.getElementById('btn-new').click()`);
// wait until the page really switched to the new match (the button never disables, so the old check was a race)
report.newMatchLoaded = await waitFor(`state.match.id !== 'synthetic-7'`, 20000);
await sleep(300);
await ev(`(() => { const c=document.querySelector('#moments .chip'); if (c) c.click(); })()`);
await ev(`(() => { document.getElementById('audience').value='coach'; document.getElementById('language').value='en'; })()`);
await ev(`document.getElementById('btn-explain').click()`);
report.newMatchSeconds = await waitFor(`!document.getElementById('error').hidden || !document.getElementById('result').hidden`, 30000);
report.newMatch = { error: await ev(`document.getElementById('error').hidden ? null : document.getElementById('error').textContent`),
                    result: await resultInfo() };
const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
if (shot.result) writeFileSync(join(outDir, "demo_page.png"), Buffer.from(shot.result.data, "base64"));

report.consoleProblems = problems;
console.log(JSON.stringify(report, null, 1));
ws.close(); edge.kill(); process.exit(0);
