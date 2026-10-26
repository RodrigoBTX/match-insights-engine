// Light and dark theme: contrast audit of every visible text, toggle, persistence, all players listed.
// Computes the WCAG contrast of each visible text element against its effective background, in both themes.
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [, , outDir] = process.argv;
mkdirSync(outDir, { recursive: true });
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9341;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "edge-th-"));
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
  if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") problems.push("console.error: " + msg.params.args.map((a) => a.value ?? a.description).join(" "));
};
const send = (method, params = {}) => new Promise((resolve) => { const i = ++id; pending.set(i, resolve); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expression) => (await send("Runtime.evaluate", { expression, returnByValue: true })).result?.result?.value;
const key = async (k, vk) => { for (const type of ["keyDown", "keyUp"]) await send("Input.dispatchKeyEvent", { type, key: k, code: k, windowsVirtualKeyCode: vk }); await sleep(250); };
async function shot(name) { const s = await send("Page.captureScreenshot", { format: "png" }); if (s.result) writeFileSync(join(outDir, name), Buffer.from(s.result.data, "base64")); }
await send("Runtime.enable"); await send("Page.enable");
await send("Page.navigate", { url: "http://127.0.0.1:8000/" });
for (let i = 0; i < 60 && !(await ev(`document.querySelectorAll('#moments .chip').length > 0`)); i++) await sleep(250);
await sleep(600);
const R = {};

// WCAG contrast of every visible text node against the first opaque background found going up the tree
const AUDIT = `(() => {
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,\/]+/).map(Number); return { r: p[0], g: p[1], b: p[2], a: p[3] ?? 1 }; };
  const lum = ({ r, g, b }) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const bgOf = (el) => { for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > 0.9) return c; } return { r: 255, g: 255, b: 255, a: 1 }; };
  const bad = [];
  const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n; (n = w.nextNode());) {
    if (!n.textContent.trim()) continue;
    const el = n.parentElement, cs = getComputedStyle(el), r = el.getBoundingClientRect();
    if (!r.width || !r.height || cs.visibility === "hidden" || cs.display === "none" || el.closest("[hidden]") || el.closest("svg") || el.closest("script,style")) continue;
    const fg = parse(cs.color); if (!fg) continue;
    const bg = bgOf(el), a = lum(fg), b = lum(bg), ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const size = parseFloat(cs.fontSize);
    if (ratio < 4.5 && !(size >= 18.66 && ratio >= 3)) bad.push({ text: n.textContent.trim().slice(0, 40), ratio: +ratio.toFixed(2), color: cs.color, bg: "rgb(" + bg.r + "," + bg.g + "," + bg.b + ")" });
  }
  return bad;
})()`;

R.playerRows = await ev(`[...document.querySelectorAll('#players .pcol')].map(c => c.querySelectorAll('button.prow').length)`);
R.expectedPlayers = await ev(`[state.match.players.filter(p => p.side === 'home').length, state.match.players.filter(p => p.side === 'away').length]`);
for (const theme of ["dark", "light"]) {
  if ((await ev(`document.documentElement.dataset.theme || 'dark'`)) !== theme) await ev(`document.getElementById('btn-theme').click()`);
  await sleep(300);
  R[theme] = { applied: await ev(`document.documentElement.dataset.theme`), button: await ev(`document.getElementById('btn-theme').textContent`),
    lowContrast: await ev(AUDIT) };
  await ev(`window.scrollTo(0, 0)`); await shot(`${theme}_top.png`);
  await ev(`document.querySelector('#moments .chip').click()`); await sleep(500);
  await shot(`${theme}_selected.png`);
  R[theme].lowContrastSelected = await ev(AUDIT);
  await ev(`document.getElementById('players').scrollIntoView()`); await sleep(300); await shot(`${theme}_players.png`);
  await ev(`document.getElementById('btn-recap').click()`);  // a recorded result: verification box, figure cards, trace
  for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#result .verify')`)); i++) await sleep(250);
  await shot(`${theme}_result.png`);
  R[theme].resultShown = await ev(`!!document.querySelector('#result .verify .linklike')`);
  R[theme].lowContrastResult = await ev(AUDIT);
  await ev(`document.getElementById('btn-about').click()`); await sleep(300); await shot(`${theme}_about.png`);
  R[theme].lowContrastAbout = await ev(AUDIT);
  await key("Escape", 27);
}
// persistence: the last theme (light) must survive a reload
await ev(`document.documentElement.dataset.theme`);
await send("Page.reload"); await sleep(1500);
R.afterReload = await ev(`document.documentElement.dataset.theme`);
R.consoleProblems = problems;
console.log(JSON.stringify(R, null, 1));
ws.close(); edge.kill(); process.exit(0);
