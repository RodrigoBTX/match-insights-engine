// What a user sees when things go wrong: failed requests, broken streams, unreadable answers, odd or invalid uploads.
// Failures are injected by replacing window.fetch in the page; uploads go through the real file input.
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [, , outDir, ...files] = process.argv;  // files: absolute paths of feeds to upload
mkdirSync(outDir, { recursive: true });
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9347;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "edge-er-"));
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  "--window-size=1500,950", "about:blank"], { stdio: "ignore" });

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
};
const send = (method, params = {}) => new Promise((resolve) => { const i = ++id; pending.set(i, resolve); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expression) => (await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true })).result?.result?.value;

await send("Runtime.enable"); await send("Page.enable"); await send("DOM.enable");
await send("Page.navigate", { url: "http://127.0.0.1:8000/" });
for (let i = 0; i < 60 && !(await ev(`document.querySelectorAll('#moments .chip').length > 0`)); i++) await sleep(250);
await sleep(500);
await ev(`window.__fetch = window.fetch; true`);

const R = { injected: {}, uploads: [] };
const state = () => ev(`({ error: document.getElementById('error').hidden ? null : document.getElementById('error').textContent,
  explainDisabled: document.getElementById('btn-explain').disabled, stepsHidden: document.getElementById('steps').hidden,
  resultHidden: document.getElementById('result').hidden })`);
const stream = (name, makeBody, status = 200) => `window.fetch = (u, o) => String(u).includes('/api/explain/stream')
  ? Promise.resolve(new Response(${makeBody}, { status: ${status}, headers: { 'Content-Type': 'application/x-ndjson' } })) : window.__fetch(u, o); true`;

async function injected(name, install) {
  await ev(`window.fetch = window.__fetch; true`);
  // clicking the selected moment again would deselect it
  await ev(`if (!state.selected) [...document.querySelectorAll('#moments .chip')].find(c => c.textContent.includes('Red card')).click(); true`);
  await sleep(200);
  await ev(install);
  await ev(`document.getElementById('btn-explain').click()`);
  await sleep(700);
  R.injected[name] = await state();
}
await injected("server down (fetch throws)", `window.fetch = (u, o) => String(u).includes('/api/explain/stream') ? Promise.reject(new TypeError('Failed to fetch')) : window.__fetch(u, o); true`);
await injected("HTTP 502 with a message", `window.fetch = (u, o) => String(u).includes('/api/explain/stream') ? Promise.resolve(new Response(JSON.stringify({ detail: 'The AI service is busy right now. Please try again in a moment.' }), { status: 502 })) : window.__fetch(u, o); true`);
await injected("HTTP 422 validation list", `window.fetch = (u, o) => String(u).includes('/api/explain/stream') ? Promise.resolve(new Response(JSON.stringify({ detail: [{ type: 'missing' }] }), { status: 422 })) : window.__fetch(u, o); true`);
await injected("HTTP 500 plain text", `window.fetch = (u, o) => String(u).includes('/api/explain/stream') ? Promise.resolve(new Response('Internal Server Error', { status: 500, statusText: 'Internal Server Error' })) : window.__fetch(u, o); true`);
await injected("error event", stream("e", `'{"event":"plan","agents":["Analyst"]}\\n{"event":"error","message":"The AI service could not be reached. Please try again in a moment."}\\n'`));
await injected("garbage line in the stream", stream("g", `'{"event":"plan","agents":["Analyst"]}\\nthis is not json\\n'`));
await injected("stream ends without a result", stream("n", `'{"event":"plan","agents":["Analyst"]}\\n'`));
await injected("connection cut mid-stream", `window.fetch = (u, o) => String(u).includes('/api/explain/stream')
  ? Promise.resolve(new Response(new ReadableStream({ start(c) { c.enqueue(new TextEncoder().encode('{"event":"plan","agents":["Analyst"]}\\n')); setTimeout(() => c.error(new TypeError('network error')), 150); } }))) : window.__fetch(u, o); true`);
// the "new synthetic match" button while the server is down
await ev(`window.fetch = () => Promise.reject(new TypeError('Failed to fetch')); true`);
await ev(`document.getElementById('btn-new').click()`); await sleep(500);
R.injected["new match while server is down"] = await state();
await ev(`window.fetch = window.__fetch; true`);
// after all of that a normal run still works
await ev(`if (!state.selected) [...document.querySelectorAll('#moments .chip')].find(c => c.textContent.includes('Red card')).click(); true`); await sleep(200);
await ev(`document.getElementById('btn-explain').click()`);
for (let i = 0; i < 40 && (await ev(`document.getElementById('result').hidden`)); i++) await sleep(250);
R.recoversAfterErrors = await state();

// uploads of odd and invalid files
const doc = (await send("DOM.getDocument")).result.root.nodeId;
const node = (await send("DOM.querySelector", { nodeId: doc, selector: "#file" })).result.nodeId;
for (const file of files) {
  await send("DOM.setFileInputFiles", { files: [file], nodeId: node });
  await sleep(1200);
  R.uploads.push({ file: file.split(/[\\/]/).pop(), ...(await ev(`({ error: document.getElementById('error').hidden ? null : document.getElementById('error').textContent,
    moments: document.querySelectorAll('#moments .chip').length, playerRows: document.querySelectorAll('#players button.prow').length,
    teams: document.querySelector('#scoreboard')?.textContent.slice(0, 60) })`)) });
}
R.consoleProblems = problems;
console.log(JSON.stringify(R, null, 1));
ws.close(); edge.kill(); process.exit(0);
