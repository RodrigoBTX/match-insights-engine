"use strict";

const NS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);

const state = { match: null, selected: null, selectedPlayer: null, busy: false };

/* ---------- helpers ---------- */
function svg(tag, attrs = {}, parent = null, text = null) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== null) n.textContent = text;
  if (parent) parent.appendChild(n);
  return n;
}
function html(tag, props = {}, children = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "text") n.textContent = v;
    else if (k === "class") n.className = v;
    else n.setAttribute(k, v);
  }
  for (const c of [].concat(children)) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  return n;
}
const colorOf = (side) => (side === "home" ? state.match.home.color : state.match.away.color);
const nameOf = (side) => state.match[side].name;
const clock = (t) => `${Math.floor(t)}'`;

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) { /* keep statusText */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json();
}

function showError(msg) {
  const box = $("error");
  box.textContent = msg || "";
  box.hidden = !msg;
}

/* ---------- scoreboard ---------- */
function renderScoreboard() {
  const m = state.match, s = m.summary;
  const box = $("scoreboard");
  box.replaceChildren();
  const team = (side) => html("div", { class: `team ${side}` }, side === "home"
    ? [html("span", { class: "swatch", style: `background:${m.home.color}` }), html("span", { class: "team-name", text: m.home.name })]
    : [html("span", { class: "team-name", text: m.away.name }), html("span", { class: "swatch", style: `background:${m.away.color}` })]);
  box.append(team("home"), html("div", { class: "score", text: `${s.score.home} – ${s.score.away}` }), team("away"));
  const stat = (label, h, a) => html("div", { class: "stat" }, [html("b", { text: `${h} – ${a}` }), html("span", { text: label })]);
  box.append(html("div", { class: "statrow" }, [
    stat("Possession %", s.possession_pct.home, s.possession_pct.away),
    stat("Shots (on target)", `${s.shots.home} (${s.on_target.home})`, `${s.shots.away} (${s.on_target.away})`),
    stat("Expected goals", s.xg.home.toFixed(2), s.xg.away.toFixed(2)),
    stat("Cards Y/R", `${s.cards.home.yellow}/${s.cards.home.red}`, `${s.cards.away.yellow}/${s.cards.away.red}`),
  ]));
  $("source").textContent = `${m.source} (${m.competition})`;
}

/* ---------- pitch ---------- */
function drawPitchBase(root) {
  const line = { fill: "none", stroke: "var(--pitch-line)", "stroke-width": 0.35 };
  svg("rect", { x: -3, y: -3, width: 111, height: 74, rx: 2, fill: "var(--pitch)" }, root);
  svg("rect", { x: 0, y: 0, width: 105, height: 68, ...line }, root);
  svg("line", { x1: 52.5, y1: 0, x2: 52.5, y2: 68, ...line }, root);
  svg("circle", { cx: 52.5, cy: 34, r: 9.15, ...line }, root);
  for (const [x, w] of [[0, 16.5], [88.5, 16.5]]) svg("rect", { x, y: 13.84, width: w, height: 40.32, ...line }, root);
  for (const [x, w] of [[0, 5.5], [99.5, 5.5]]) svg("rect", { x, y: 24.84, width: w, height: 18.32, ...line }, root);
  svg("rect", { x: -1.5, y: 30.34, width: 1.5, height: 7.32, ...line }, root);
  svg("rect", { x: 105, y: 30.34, width: 1.5, height: 7.32, ...line }, root);
  svg("text", { x: 2, y: -0.9, "font-size": 2.6 }, root, `${state.match.home.short} attacks →`);
  svg("text", { x: 103, y: -0.9, "font-size": 2.6, "text-anchor": "end" }, root, `← ${state.match.away.short} attacks`);
  const defs = svg("defs", {}, root);
  for (const side of ["home", "away"]) {
    const mk = svg("marker", { id: `arrow-${side}`, viewBox: "0 0 6 6", refX: 5, refY: 3, markerWidth: 2.4, markerHeight: 2.4, orient: "auto" }, defs);
    svg("path", { d: "M0,0 L6,3 L0,6 z", fill: colorOf(side) }, mk);
  }
}

/* Press line = mean distance from own goal where the side wins the ball, before and after the shift. */
function drawPressLines(g, moment) {
  const f = moment.facts, side = moment.side, col = colorOf(side);
  const before = f.window_before_10_min.press_height_m[side], after = f.window_after_10_min.press_height_m[side];
  if (before == null || after == null) return;
  const abs = (h) => (side === "home" ? h : 105 - h);
  for (const [h, label, dash, y] of [[before, `before ${before} m`, "2 1.5", 6], [after, `after ${after} m`, "none", 62]]) {
    svg("line", { x1: abs(h), y1: 0, x2: abs(h), y2: 68, stroke: col, "stroke-width": 0.8, "stroke-dasharray": dash }, g);
    svg("text", { x: abs(h) + (side === "home" ? 1 : -1), y, "text-anchor": side === "home" ? "start" : "end",
      style: `fill:${col}`, "font-weight": 700 }, g, label);
  }
}

function shotTitle(e) {
  const xg = e.xg != null ? ` · xG ${e.xg.toFixed(2)}` : "";
  return `${clock(e.t)} ${e.player || ""} (${nameOf(e.side)})${xg} · ${e.outcome || e.type}`;
}

function renderPitch() {
  const root = $("pitch");
  root.replaceChildren();
  drawPitchBase(root);
  const m = state.match;
  const moment = m.moments.find((x) => x.id === state.selected);
  const player = m.players.find((p) => p.id === state.selectedPlayer);
  const shots = m.events.filter((e) => e.type === "shot" || e.type === "goal");
  const dim = !!moment || !!player;

  const layer = svg("g", { opacity: dim ? 0.18 : 1 }, root);
  for (const e of shots) {
    const r = 0.9 + (e.xg ?? 0.05) * 6;
    const c = svg("circle", { cx: e.x, cy: e.y, r, fill: colorOf(e.side), "fill-opacity": 0.72,
      stroke: e.type === "goal" ? "#fff" : colorOf(e.side), "stroke-width": e.type === "goal" ? 0.7 : 0.25 }, layer);
    svg("title", {}, c, shotTitle(e));
  }

  if (moment) {
    $("pitch-title").textContent = `Replay – ${moment.title} (${moment.facts.minute})`;
    const byId = new Map(m.events.map((e) => [e.id, e]));
    const seq = moment.event_ids.map((id) => byId.get(id)).filter(Boolean);
    const g = svg("g", {}, root);
    if (moment.type === "tactical_shift") drawPressLines(g, moment);
    seq.forEach((e, i) => {
      const style = `animation-delay:${i * 0.22}s`;
      const col = colorOf(e.side);
      if (e.type === "pass" && e.ex != null) {
        svg("line", { x1: e.x, y1: e.y, x2: e.ex, y2: e.ey, stroke: col, "stroke-width": 0.7, class: "reveal", style,
          "marker-end": `url(#arrow-${e.side})` }, g);
      } else if (e.type === "shot" || e.type === "goal") {
        const n = svg("g", { class: "reveal", style }, g);
        svg("line", { x1: e.x, y1: e.y, x2: e.side === "home" ? 105 : 0, y2: 34, stroke: col, "stroke-width": 0.5, "stroke-dasharray": "1.2 1" }, n);
        const c = svg("circle", { cx: e.x, cy: e.y, r: 1.9, fill: e.type === "goal" ? "#fff" : col, stroke: col, "stroke-width": 0.8 }, n);
        svg("title", {}, c, shotTitle(e));
      } else if (e.type === "red_card" || e.type === "yellow_card") {
        svg("rect", { x: e.x - 1.2, y: e.y - 1.8, width: 2.4, height: 3.6, rx: 0.4, class: "reveal", style,
          fill: e.type === "red_card" ? "#ff3b3b" : "#ffd23b" }, g);
      } else if (e.type === "tackle" || e.type === "interception" || e.type === "corner" || e.type === "foul") {
        const d = svg("rect", { x: e.x - 1.1, y: e.y - 1.1, width: 2.2, height: 2.2, transform: `rotate(45 ${e.x} ${e.y})`,
          fill: col, class: "reveal", style }, g);
        svg("title", {}, d, `${clock(e.t)} ${e.type} – ${e.player || ""}`);
      }
    });
  } else if (player) {
    drawPlayer(root, player);
  } else {
    $("pitch-title").textContent = "Shot map";
  }

  const lg = $("pitch-legend");
  lg.replaceChildren();
  for (const side of ["home", "away"]) {
    const s = html("span", {}, [html("i", { class: "dot", style: `background:${colorOf(side)}` }), nameOf(side)]);
    lg.appendChild(s);
  }
  const area = moment && (moment.type === "tactical_shift" || moment.type === "chaotic_spell");
  if (player) {
    lg.appendChild(html("span", { text: "Bright arrows = progressive passes · circles = shots · ◇ = ball won" }));
    return;
  }
  lg.appendChild(html("span", { text: !moment ? "Size = xG · white ring = goal"
    : moment.type === "tactical_shift" ? "Lines = press height before/after · ◇ = ball won"
    : area ? "◇ = ball won or lost during the period" : "Arrows = passes · ◇ = turnover" }));
}

/* One player's passes (progressive ones highlighted), shots and ball wins. */
function drawPlayer(root, p) {
  const m = state.match, col = colorOf(p.side);
  $("pitch-title").textContent = `Player – ${p.name} (${p.position}, ${p.team})`;
  const g = svg("g", {}, root);
  for (const e of m.events.filter((ev) => ev.pid === p.id)) {
    if (e.type === "pass" && e.ex != null) {
      svg("line", { x1: e.x, y1: e.y, x2: e.ex, y2: e.ey, stroke: col, "stroke-width": e.prog ? 0.9 : 0.35,
        "stroke-opacity": e.prog ? 1 : 0.28, ...(e.prog ? { "marker-end": `url(#arrow-${e.side})` } : {}) }, g);
    } else if (e.type === "shot" || e.type === "goal") {
      const c = svg("circle", { cx: e.x, cy: e.y, r: 1.2 + (e.xg ?? 0.05) * 6, fill: e.type === "goal" ? "#fff" : col,
        "fill-opacity": 0.85, stroke: col, "stroke-width": 0.8 }, g);
      svg("title", {}, c, shotTitle(e));
    } else if (e.type === "tackle" || e.type === "interception") {
      svg("rect", { x: e.x - 1, y: e.y - 1, width: 2, height: 2, transform: `rotate(45 ${e.x} ${e.y})`, fill: col }, g);
    }
  }
}

/* ---------- players ---------- */
function renderPlayers() {
  const m = state.match, box = $("players");
  box.replaceChildren();
  const best = m.players[0];
  $("potm").textContent = best ? `Highest impact: ${best.name} (${best.team}) · ${best.impact}` : "";
  const maxImpact = Math.max(...m.players.map((p) => p.impact), 1);
  for (const side of ["home", "away"]) {
    const col = html("div", { class: "pcol" }, [html("h3", { text: m[side].name, style: `border-color:${m[side].color}` })]);
    col.appendChild(html("div", { class: "prow head" }, ["", "Player", "Impact", "G", "xG", "CC", "Prog"].map((t) => html("span", { text: t }))));
    for (const p of m.players.filter((q) => q.side === side).slice(0, 6)) {
      const row = html("button", { class: "prow", type: "button", "aria-pressed": p.id === state.selectedPlayer,
        title: `${p.name}: ${p.passes} passes, ${p.progressive_passes} progressive, ${p.chances_created} chances created, ${p.tackles + p.interceptions} ball wins` }, [
        html("span", { class: "rank", text: String(p.rank_in_team) }),
        html("span", { class: "pname" }, [p.name, html("small", { text: ` ${p.position}` })]),
        html("span", { class: "impact" }, [html("i", { style: `width:${(100 * p.impact) / maxImpact}%;background:${m[side].color}` }), html("b", { text: p.impact.toFixed(1) })]),
        html("span", { text: String(p.goals) }), html("span", { text: p.xg.toFixed(2) }),
        html("span", { text: String(p.chances_created) }), html("span", { text: String(p.progressive_passes) }),
      ]);
      row.addEventListener("click", () => selectPlayer(p.id));
      col.appendChild(row);
    }
    box.appendChild(col);
  }
}

/* ---------- momentum timeline ---------- */
const MARK = { goal: "G", red_card: "R", big_chance: "C", tactical_shift: "T", chaotic_spell: "≈" };

/* ---------- control vs chaos ---------- */
const CHAOS_COLOR = "#c77dff";
const NEUTRAL_COLOR = "#5b6b64";

function stateLabel(windowState) {
  const m = state.match;
  return { home_control: `${m.home.name} in control`, away_control: `${m.away.name} in control`,
    balanced: "Balanced", chaotic: "Chaotic" }[windowState] || windowState;
}

function renderControl() {
  const root = $("control");
  root.replaceChildren();
  const m = state.match, W = 960, L = 8, R = 8, y = 6, h = 38;
  const defs = svg("defs", {}, root);
  const pat = svg("pattern", { id: "chaos-hatch", width: 8, height: 8, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" }, defs);
  svg("rect", { width: 8, height: 8, fill: CHAOS_COLOR, "fill-opacity": 0.35 }, pat);
  svg("rect", { width: 3, height: 8, fill: CHAOS_COLOR }, pat);
  const cw = (W - L - R) / m.control.length;
  m.control.forEach((w, i) => {
    const x = L + i * cw;
    const fill = w.state === "chaotic" ? "url(#chaos-hatch)" : w.state === "home_control" ? m.home.color
      : w.state === "away_control" ? m.away.color : NEUTRAL_COLOR;
    const r = svg("rect", { x: x + 1, y, width: cw - 2, height: h, rx: 4, fill, "fill-opacity": w.state === "balanced" ? 0.55 : 0.9 }, root);
    svg("title", {}, r, `${w.start}'–${w.end}' · ${stateLabel(w.state)}\ncontrol ${m.home.short} ${w.control_score.home} / ${m.away.short} ${w.control_score.away}\n${w.sequences_per_min} sequences/min · ${w.avg_passes_per_sequence} passes/sequence`);
    if (i % 3 === 0) svg("text", { x: x + cw / 2, y: 62, "text-anchor": "middle" }, root, `${w.start}'`);
  });
  const lg = $("control-legend");
  lg.replaceChildren();
  const item = (color, label, hatched) => html("span", {}, [html("i", { class: "dot", style: `background:${hatched ? `repeating-linear-gradient(45deg,${color},${color} 2px,transparent 2px,transparent 4px)` : color}` }), label]);
  lg.append(item(m.home.color, `${m.home.short} control`), item(m.away.color, `${m.away.short} control`),
    item(NEUTRAL_COLOR, "Balanced"), item(CHAOS_COLOR, "Chaotic", true));
}

function renderMomentum() {
  const root = $("momentum");
  root.replaceChildren();
  const m = state.match, W = 960, L = 36, R = 12, base = 112, amp = 62;
  const xs = (min) => L + (min / 93) * (W - L - R);
  svg("line", { x1: L, y1: base, x2: W - R, y2: base, stroke: "var(--line)" }, root);
  svg("line", { x1: xs(45), y1: 34, x2: xs(45), y2: 176, stroke: "var(--line)", "stroke-dasharray": "4 4" }, root);
  svg("text", { x: xs(45) + 4, y: 46 }, root, "HT");
  for (const t of [0, 15, 30, 45, 60, 75, 90]) svg("text", { x: xs(t), y: 188, "text-anchor": "middle" }, root, `${t}'`);
  svg("text", { x: 4, y: base - amp + 4 }, root, m.home.short);
  svg("text", { x: 4, y: base + amp + 4 }, root, m.away.short);
  const bw = (W - L - R) / 93 - 1.5;
  for (const p of m.momentum) {
    const h = Math.abs(p.value) * amp;
    if (!h) continue;
    svg("rect", { x: xs(p.minute) - bw / 2, y: p.value > 0 ? base - h : base, width: bw, height: h, rx: 1.5,
      fill: p.value > 0 ? m.home.color : m.away.color, "fill-opacity": 0.8 }, root);
  }
  for (const mo of m.moments) {
    const x = xs(mo.minute + mo.second / 60);
    const sel = mo.id === state.selected;
    svg("line", { x1: x, y1: 30, x2: x, y2: base, stroke: colorOf(mo.side), "stroke-opacity": sel ? 0.9 : 0.35, "stroke-dasharray": "2 3" }, root);
    const g = svg("g", { class: "marker", tabindex: 0, role: "button", "aria-label": `${mo.title} at ${mo.facts.minute}`,
      "aria-pressed": sel }, root);
    svg("circle", { class: "hit", cx: x, cy: 20, r: 12, fill: "var(--surface)", stroke: colorOf(mo.side), "stroke-width": sel ? 3 : 1.5 }, g);
    svg("text", { x, y: 24, "text-anchor": "middle", "font-weight": 700, style: "fill:var(--text)" }, g, MARK[mo.type] || "•");
    svg("title", {}, g, `${mo.facts.minute} ${mo.title}`);
    g.addEventListener("click", () => select(mo.id));
    g.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(mo.id); } });
  }
}

function renderMoments() {
  const box = $("moments");
  box.replaceChildren();
  for (const mo of state.match.moments) {
    const b = html("button", { class: "chip", type: "button", "aria-pressed": mo.id === state.selected }, [
      html("span", { class: "min", text: mo.facts.minute }),
      html("i", { class: "dot", style: `background:${colorOf(mo.side)}` }),
      mo.title,
    ]);
    b.addEventListener("click", () => select(mo.id));
    box.appendChild(b);
  }
}

/* ---------- xG and possession ---------- */
function axes(root, W, H, L, B, ticks, fmt) {
  for (const v of ticks) {
    const y = B - v.pos;
    svg("line", { x1: L, y1: y, x2: W - 8, y2: y, stroke: "var(--line)" }, root);
    svg("text", { x: L - 6, y: y + 4, "text-anchor": "end" }, root, fmt(v.value));
  }
}

function renderXG() {
  const root = $("xg");
  root.replaceChildren();
  const m = state.match, W = 460, H = 170, L = 34, B = 142, T = 12;
  const last = m.xg[m.xg.length - 1];
  const max = Math.max(1, Math.ceil(Math.max(last.home, last.away) * 2) / 2);
  const x = (min) => L + (min / 92) * (W - L - 54);
  const y = (v) => B - (v / max) * (B - T);
  const ticks = [0, max / 2, max].map((v) => ({ value: v, pos: B - y(v) }));
  axes(root, W, H, L, B, ticks, (v) => v.toFixed(1));
  for (const t of [0, 45, 90]) svg("text", { x: x(t), y: 160, "text-anchor": "middle" }, root, `${t}'`);
  for (const side of ["home", "away"]) {
    const pts = m.xg.map((p) => `${x(p.minute)},${y(p[side])}`).join(" ");
    svg("polyline", { points: pts, fill: "none", stroke: colorOf(side), "stroke-width": 2.5, "stroke-linejoin": "round" }, root);
    svg("text", { x: x(92) + 6, y: y(last[side]) + 4, style: `fill:${colorOf(side)}`, "font-weight": 700 }, root, `${m[side].short} ${last[side].toFixed(2)}`);
  }
  for (const mo of m.moments.filter((q) => q.type === "goal")) {
    const p = m.xg[Math.min(mo.minute, 92)];
    svg("circle", { cx: x(mo.minute), cy: y(p[mo.side]), r: 4.5, fill: "#fff", stroke: colorOf(mo.side), "stroke-width": 2 }, root);
  }
}

function renderPossession() {
  const root = $("poss");
  root.replaceChildren();
  const m = state.match, W = 460, L = 34, B = 142, T = 12;
  const n = m.possession.length, bw = (W - L - 8) / n - 3;
  axes(root, W, 170, L, B, [0, 50, 100].map((v) => ({ value: v, pos: (v / 100) * (B - T) })), (v) => `${v}%`);
  m.possession.forEach((w, i) => {
    const x = L + i * ((W - L - 8) / n) + 1.5, hh = (w.home / 100) * (B - T);
    svg("rect", { x, y: B - hh, width: bw, height: hh, fill: m.home.color, "fill-opacity": 0.85 }, root);
    svg("rect", { x, y: T, width: bw, height: B - T - hh, fill: m.away.color, "fill-opacity": 0.85 }, root);
    if (i % 3 === 0) svg("text", { x: x + bw / 2, y: 160, "text-anchor": "middle" }, root, `${w.start}'`);
  });
}

/* ---------- selection ---------- */
function hasSelection() {
  return state.selected !== null || state.selectedPlayer !== null;
}

function refreshSelection() {
  const mo = state.match.moments.find((x) => x.id === state.selected);
  const pl = state.match.players.find((p) => p.id === state.selectedPlayer);
  $("selected-label").textContent = mo ? `${mo.facts.minute} · ${mo.title}` : pl ? `${pl.name} · ${pl.team}` : "Whole match";
  $("btn-explain").textContent = pl ? "Explain this player" : "Explain this moment";
  $("btn-explain").disabled = !hasSelection() || state.busy;
  $("result").hidden = true;
  showError("");
  renderPitch(); renderMomentum(); renderMoments(); renderPlayers();
}

function select(id) {
  state.selected = state.selected === id ? null : id;
  state.selectedPlayer = null;
  refreshSelection();
}

function selectPlayer(pid) {
  state.selectedPlayer = state.selectedPlayer === pid ? null : pid;
  state.selected = null;
  refreshSelection();
}

/* ---------- agents ---------- */
const ROLE = {
  Analyst: "Analyst – querying the data with tools",
  Narrator: "Narrator – explaining why it matters",
  Verifier: "Verifier – checking every claim against the data",
  Localiser: "Localiser – adapting audience and language",
};

function setBusy(on) {
  state.busy = on;
  $("btn-recap").disabled = on;
  $("btn-explain").disabled = on || !hasSelection();
  const steps = $("steps");
  steps.hidden = !on;
  steps.replaceChildren();
}

function renderSteps(agents) {
  const steps = $("steps");
  steps.replaceChildren(...agents.map((a) => {
    const row = html("div", { class: "step", "data-agent": a }, [html("i"), html("span", { text: ROLE[a] || a })]);
    return row;
  }));
}

function markStep(agent, status, seconds) {
  const row = $("steps").querySelector(`[data-agent="${agent}"]`);
  if (!row) return;
  row.className = `step ${status}`;
  if (status === "done") row.lastChild.textContent = `${ROLE[agent] || agent} · ${seconds}s`;
}

function verificationBadge(v) {
  if (!v) return null;
  const num = v.numeric_check || { checked: 0, unverified: [] };
  const issues = v.issues || [];
  const clean = issues.length === 0 && num.unverified.length === 0;
  const parts = [`Verifier: ${v.claims_checked} claims checked, ${issues.length} issue${issues.length === 1 ? "" : "s"}`,
    `Numeric guard: ${num.checked} figures, ${num.unverified.length ? `not traced to data: ${num.unverified.join(", ")}` : "all traced to data"}`];
  const box = html("div", { class: `verify ${clean ? "ok" : "warn"}` }, [
    html("b", { text: clean ? "Verified against the data" : "Check these figures" }),
    ...parts.map((p) => html("span", { text: p })),
    ...issues.map((i) => html("span", { text: `• ${i}` })),
  ]);
  return box;
}

function renderResult(r) {
  const box = $("result");
  box.replaceChildren();
  box.append(html("h3", { text: r.headline || "" }), html("p", { text: r.explanation || "" }));
  if (r.tactical_takeaway) box.append(html("div", { class: "takeaway", text: r.tactical_takeaway }));
  const badge = verificationBadge(r.verification);
  if (badge) box.append(badge);
  if (r.stat_chips?.length) {
    box.append(html("div", { class: "chips" }, r.stat_chips.map((c) =>
      html("div", { class: "statchip" }, [html("b", { text: String(c.value) }), html("span", { text: String(c.label) })]))));
  }
  if (r.findings?.length) {
    box.append(html("details", {}, [html("summary", { text: "Grounded findings (from the data)" }),
      html("ul", {}, r.findings.map((f) => html("li", { text: f })))]));
  }
  if (r.trace?.length) {
    const li = r.trace.map((t) => t.tool
      ? html("li", {}, [`${t.agent} called `, html("code", { text: `${t.tool}(${Object.values(t.args).join(", ")})` })])
      : html("li", { text: `${t.agent} finished in ${t.seconds}s` }));
    box.append(html("details", { class: "trace" }, [html("summary", { text: "How the agents got here" }), html("ul", {}, li)]));
  }
  if (r.cached) box.append(html("span", { class: "tag", text: "served from cache" }));
  box.hidden = false;
}

async function runAgents(momentId, playerId = null) {
  showError("");
  $("result").hidden = true;
  setBusy(true);
  try {
    const res = await fetch("/api/explain/stream", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ match_id: state.match.id, moment_id: momentId, player_id: playerId,
        audience: $("audience").value, language: $("language").value }),
    });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "", result = null;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (!line) continue;
        const ev = JSON.parse(line);
        if (ev.event === "plan") renderSteps(ev.agents);
        else if (ev.event === "start") markStep(ev.agent, "active");
        else if (ev.event === "done") markStep(ev.agent, "done", ev.seconds);
        else if (ev.event === "result") result = ev.result;
        else if (ev.event === "error") throw new Error(ev.message);
      }
    }
    if (!result) throw new Error("The agents returned no result");
    renderResult(result);
  } catch (err) {
    showError(err.message);
  } finally {
    setBusy(false);
  }
}

/* ---------- match loading ---------- */
function setMatch(data) {
  state.match = data;
  state.selected = null;
  state.selectedPlayer = null;
  $("selected-label").textContent = "Whole match";
  $("btn-explain").textContent = "Explain this moment";
  $("btn-explain").disabled = true;
  $("result").hidden = true;
  showError("");
  renderScoreboard(); renderPitch(); renderMomentum(); renderMoments(); renderControl(); renderPlayers();
  renderXG(); renderPossession();
}

async function init() {
  try {
    const cfg = await api("/api/config");
    const sel = $("language");
    for (const [code, name] of Object.entries(cfg.languages)) sel.appendChild(html("option", { value: code, text: name }));
    setMatch(await api(`/api/match/${cfg.matches[0]}`));
    const wantedPlayer = Number(new URLSearchParams(location.search).get("player"));  // e.g. /?player=6
    if (wantedPlayer && state.match.players.some((p) => p.id === wantedPlayer)) selectPlayer(wantedPlayer);
    const wanted = new URLSearchParams(location.search).get("moment");  // deep link, e.g. /?moment=m1
    if (wanted && state.match.moments.some((m) => m.id === wanted)) {
      select(wanted);
      if (new URLSearchParams(location.search).get("explain") === "1") runAgents(wanted);  // e.g. /?moment=m7&explain=1
    }
  } catch (err) {
    showError(`Could not load the match: ${err.message}`);
  }
}

$("btn-explain").addEventListener("click", () => {
  if (state.selectedPlayer !== null) runAgents(null, state.selectedPlayer);
  else if (state.selected) runAgents(state.selected);
});
$("btn-recap").addEventListener("click", () => runAgents(null));
$("btn-new").addEventListener("click", async () => {
  try { setMatch(await api("/api/match/synthetic", { method: "POST" })); } catch (err) { showError(err.message); }
});
$("file").addEventListener("change", async (ev) => {
  const f = ev.target.files[0];
  if (!f) return;
  const body = new FormData();
  body.append("file", f);
  try { setMatch(await api("/api/match/upload", { method: "POST", body })); } catch (err) { showError(err.message); }
  ev.target.value = "";
});

init();
