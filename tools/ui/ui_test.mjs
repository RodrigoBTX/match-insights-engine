// Drives Edge through the DevTools protocol: loads the app, clicks a moment, runs the agents, captures evidence.
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [, , outDir, momentText, audience = "casual_fan", language = "en"] = process.argv;
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9333;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const profile = mkdtempSync(join(tmpdir(), "edge-ui-"));
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--window-size=1440,1400", "about:blank"], { stdio: "ignore" });

async function targetWs() {
  for (let i = 0; i < 40; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch (_) { /* edge still starting */ }
    await sleep(250);
  }
  throw new Error("Edge DevTools endpoint not reachable");
}

const ws = new WebSocket(await targetWs());
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pending = new Map();
const problems = [];
ws.onmessage = (m) => {
  const msg = JSON.parse(m.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  if (msg.method === "Runtime.exceptionThrown") problems.push("EXCEPTION: " + msg.params.exceptionDetails.exception?.description);
  if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") problems.push("console.error: " + msg.params.args.map((a) => a.value ?? a.description).join(" "));
};
const send = (method, params = {}) => new Promise((resolve) => { const i = ++id; pending.set(i, resolve); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expression) => (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result?.result?.value;
async function shot(name) {
  const r = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  writeFileSync(join(outDir, name), Buffer.from(r.result.data, "base64"));
}

await send("Runtime.enable");
await send("Page.enable");
await send("Page.navigate", { url: "http://127.0.0.1:8000/" });
for (let i = 0; i < 40 && !(await evaluate(`document.querySelectorAll('#moments .chip').length > 0`)); i++) await sleep(250);

const report = {};
report.chips = await evaluate(`document.querySelectorAll('#moments .chip').length`);
report.controlCells = await evaluate(`document.querySelectorAll('#control rect').length`);

// 1. click the chosen moment chip
const isPlayer = momentText.startsWith("player:");
const sel = isPlayer ? `#players button.prow` : `#moments .chip`;
const needle = isPlayer ? momentText.slice(7) : momentText;
report.clicked = await evaluate(`(() => { const c=[...document.querySelectorAll(${JSON.stringify(sel)})].find(b=>b.textContent.includes(${JSON.stringify(needle)})); if(!c) return false; c.click(); return true; })()`);
await sleep(600);
report.pitchTitle = await evaluate(`document.getElementById('pitch-title').textContent`);
report.explainButton = await evaluate(`document.getElementById('btn-explain').textContent + (document.getElementById('btn-explain').disabled ? ' (disabled)' : '')`);
report.playerRows = await evaluate(`document.querySelectorAll('#players button.prow').length`);
report.potm = await evaluate(`document.getElementById('potm').textContent`);
report.pressedRows = await evaluate(`document.querySelectorAll('#players button.prow[aria-pressed="true"]').length`);
await shot("ui_selected.png");

// 2. choose audience and language, run the agents
await evaluate(`(() => { const a=document.getElementById('audience'); a.value=${JSON.stringify(audience)}; const l=document.getElementById('language'); l.value=${JSON.stringify(language)}; })()`);
await evaluate(`document.getElementById('btn-explain').click()`);
const t0 = Date.now();
const stepLog = [];
for (let i = 0; i < 200; i++) {
  await sleep(500);
  const snap = await evaluate(`[...document.querySelectorAll('#steps .step')].map(s => s.className.replace('step','').trim() + ':' + s.textContent.slice(0,22)).join(' | ')`);
  if (snap && stepLog[stepLog.length - 1]?.snap !== snap) stepLog.push({ t: ((Date.now() - t0) / 1000).toFixed(1), snap });
  if (await evaluate(`!document.getElementById('result').hidden || !document.getElementById('error').hidden`)) break;
}
report.stepProgress = stepLog;
report.result = await evaluate(`(() => { const r=document.getElementById('result'); return r.hidden ? null : { h3: r.querySelector('h3')?.textContent, verify: r.querySelector('.verify')?.textContent, chips: r.querySelectorAll('.statchip').length, details: r.querySelectorAll('details').length }; })()`);
report.error = await evaluate(`document.getElementById('error').hidden ? null : document.getElementById('error').textContent`);
await sleep(500);
await shot("ui_explain.png");
report.consoleProblems = problems;
console.log(JSON.stringify(report, null, 1));

ws.close();
edge.kill();
process.exit(0);
