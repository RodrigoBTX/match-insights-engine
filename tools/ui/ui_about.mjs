// "How it works" panel, the try-this suggestions, and how the page shows an automatic revision.
// The revision is checked by calling the page's own functions with a simulated result (a real one cannot be forced).
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [, , outDir] = process.argv;
mkdirSync(outDir, { recursive: true });
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const PORT = 9339;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const profile = mkdtempSync(join(tmpdir(), "edge-ab-"));
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

// 1. the panel
R.aboutHiddenAtStart = await ev(`document.getElementById('about-backdrop').hidden`);
await ev(`document.getElementById('btn-about').click()`);
await sleep(300);
R.about = await ev(`(() => ({ open: !document.getElementById('about-backdrop').hidden,
  nodes: [...document.querySelectorAll('#about-backdrop .flow .node b')].map(b => b.textContent),
  sections: [...document.querySelectorAll('#about-backdrop h3')].map(h => h.textContent),
  quality: document.getElementById('about-quality').textContent.slice(0, 160),
  links: [...document.querySelectorAll('#about-backdrop a')].map(a => a.href),
  focusOnClose: document.activeElement?.id }))()`);
await shot("about_open.png");
await key("Escape", 27);
R.aboutClosedByEsc = await ev(`document.getElementById('about-backdrop').hidden`);
R.focusReturnedToButton = await ev(`document.activeElement?.id === 'btn-about'`);
await ev(`document.getElementById('btn-about').click()`);
await ev(`document.getElementById('about-backdrop').dispatchEvent(new MouseEvent('click', { bubbles: true }))`);
R.aboutClosedByBackdropClick = await ev(`document.getElementById('about-backdrop').hidden`);

// 2. the try-this suggestions
R.tips = await ev(`[...document.querySelectorAll('#info .tip')].map(b => b.textContent)`);
await shot("tips.png");
await ev(`document.querySelector('#info .tip').click()`);
await sleep(300);
R.afterTip = await ev(`(() => ({ tag: document.querySelector('#info .info-tag')?.textContent, title: document.querySelector('#info .info-title')?.textContent,
  chips: document.querySelectorAll('#info .statchip').length }))()`);
R.tipsGoneAfterSelecting = await ev(`document.querySelectorAll('#info .tip').length === 0`);

// 3. how a revision is shown (simulated result, the page's real functions)
await ev(`showRevise(["The checks flagged: headline: A chaotic spell concerns both teams, but the text names only one of them."])`);
R.reviseShown = await ev(`(() => { const b = document.getElementById('revise'); return { visible: !b.hidden, text: b.textContent }; })()`);
await ev(`setBusy(false)`);
R.reviseHiddenWhenDone = await ev(`document.getElementById('revise').hidden`);
await ev(`renderResult({ headline: "Both teams lose control for ten minutes", explanation: "e", tactical_takeaway: "t", stat_chips: [], findings: [],
  verification: { verdict: "verified", claims_checked: 3, issues: [], numeric_check: { checked: 4, unverified: [] } },
  trace: [{ agent: "Analyst", seconds: 5.1 }, { agent: "Checks", note: "flagged a problem, revised once" }, { agent: "Narrator", seconds: 2.0 }],
  revision: { attempted: true, kept: "revised", fixed: true, first_problems: ["The checks flagged: headline: names only one team"] } })`);
R.revisionNote = await ev(`(() => { const r = document.getElementById('result'); return { note: r.querySelector('.fallback-note')?.textContent,
  traceHasNote: [...r.querySelectorAll('.trace li')].some(li => li.textContent.includes('Checks: flagged a problem')),
  traceNoUndefined: ![...r.querySelectorAll('.trace li')].some(li => /undefined|null/.test(li.textContent)) }; })()`);
await ev(`renderResult({ headline: "h", explanation: "e", tactical_takeaway: "t", stat_chips: [], findings: [],
  verification: { verdict: "verified", claims_checked: 1, issues: ["x"], numeric_check: { checked: 1, unverified: [] } }, trace: [],
  revision: { attempted: true, kept: "first", fixed: false, first_problems: ["The checks flagged: x"] } })`);
R.revisionNoteWhenNotImproved = await ev(`document.querySelector('#result .fallback-note')?.textContent`);
await shot("revision_note.png");

R.consoleProblems = problems;
console.log(JSON.stringify(R, null, 1));
ws.close(); edge.kill(); process.exit(0);
