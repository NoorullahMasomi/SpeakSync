"use strict";
/* SpeakSync - the app page. Talks only to the small server on this PC. */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const KEY = new URLSearchParams(location.search).get("k") || "";

// ============================================================ words (English + other languages)
let EN = {}, TR = {}, uiLang = "en";
function t(key, vars) {
  let s = TR[key] ?? EN[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
  return s;
}
async function loadLang(lang) {
  if (!Object.keys(EN).length) EN = await (await fetch("/static/i18n/en.json")).json();
  TR = lang === "en" ? {} : await (await fetch(`/static/i18n/${lang}.json`)).json().catch(() => ({}));
  uiLang = lang;
  document.documentElement.lang = lang;
  document.documentElement.dir = TR._dir || EN._dir || "ltr";
  $$("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
  $("#uiLang").value = lang;
  refreshTexts();
}
function refreshTexts() {
  if (state.project) { drawParts(); drawRecList(); showRecPart(); drawMake(); markLabel(); }
  drawHome();
}

// ============================================================ server
async function api(method, path, body) {
  const opt = { method, headers: { "X-Key": KEY } };
  if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(path, opt); } catch (e) { toast(t("err_server"), "bad"); throw e; }
  const j = await r.json().catch(() => ({}));
  if (j && j.ok === false && j.error) toast(j.error, "bad");
  return j;
}
const media = (p, stamp) => `${p}?k=${encodeURIComponent(KEY)}&t=${stamp || Date.now()}`;
let toastT = 0;
function toast(msg, cls = "") {
  const el = $("#toast"); el.textContent = msg; el.className = cls; el.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => el.hidden = true, cls === "bad" ? 7000 : 3500);
}
function esc(s) { return String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function fmt(sec, tenth = true) {
  if (sec == null || isNaN(sec)) return "–";
  sec = Math.max(0, sec);
  const m = Math.floor(sec / 60), s = sec - m * 60;
  const ss = tenth ? s.toFixed(1).padStart(4, "0") : String(Math.floor(s)).padStart(2, "0");
  return `${m}:${ss}`;
}
function parseT(txt) {
  const m = String(txt).trim().match(/^(?:(\d+):)?(?:(\d+):)?(\d+(?:[.,]\d+)?)$/);
  if (!m) return null;
  const c = parseFloat(m[3].replace(",", "."));
  if (m[1] && m[2]) return +m[1] * 3600 + +m[2] * 60 + c;
  if (m[1]) return +m[1] * 60 + c;
  return c;
}
const newId = () => "p_" + [...crypto.getRandomValues(new Uint8Array(4))].map(b => b.toString(16).padStart(2, "0")).join("");

// ============================================================ app state
const state = { project: null, parts: [], sel: null, tab: "mark", info: null };
const vid = document.createElement("video");
vid.playsInline = true; vid.preload = "auto";
const P = () => state.project;

function setProject(info, keepParts = false) {
  const first = !state.project || state.project.folder !== info.folder;
  state.project = info;
  if (!keepParts || first) state.parts = info.parts.map(p => ({ id: p.id, start: p.start, end: p.end, text: p.text }));
  state.takes = Object.fromEntries(info.parts.map(p => [p.id, p.take ? p.stamp : 0]));
  if (first) {
    vid.src = info.video_ok ? media("/media/video", info.updated) : "";
    state.sel = null; markOpen = null; view = null; recIdx = -1;
  }
  $("#projName").textContent = info.name;
  $("#tabs").hidden = false; $("#closeBtn").hidden = false; $("#home").hidden = true;
  if (first) showTab(state.parts.some(p => p.start != null) ? (Object.values(state.takes).some(Boolean) ? "record" : "mark") : "mark");
  else refreshTexts();
  drawMissing();
}
function drawMissing() {
  $$(".vbox .missing").forEach(e => e.remove());
  if (P() && !P().video_ok) {
    for (const box of ["#markVideo", "#recVideo"]) {
      const d = document.createElement("div"); d.className = "missing";
      d.innerHTML = `<div><p>${esc(t("video_missing"))}</p><p class="dim" style="font-size:13px">${esc(P().video)}</p><button class="primary">${esc(t("find_video"))}</button></div>`;
      d.querySelector("button").onclick = async () => { const r = await api("POST", "/api/project/relink"); if (r.ok) { state.project = null; setProject(r.project); } };
      $(box).appendChild(d);
    }
  }
}
function showTab(tab) {
  if (phase !== "idle" && tab !== "record") stopRec();
  state.tab = tab;
  for (const s of ["mark", "record", "make"]) $("#" + s).hidden = s !== tab;
  $$("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === tab));
  vid.pause(); playUntil = null;
  if (tab === "mark") { $("#markVideo").prepend(vid); vid.muted = false; drawParts(); requestAnimationFrame(drawTimeline); }
  if (tab === "record") { $("#recVideo").prepend(vid); vid.muted = !$("#hearChk").checked; openMicOnce(); drawRecList(); pickRecPart(); }
  if (tab === "make") { drawMake(); pollExport(); }
  markLabel();
}
async function closeProject() {
  stopRec(); await flushSave();
  await api("POST", "/api/project/close");
  state.project = null; vid.removeAttribute("src"); vid.load();
  for (const s of ["mark", "record", "make"]) $("#" + s).hidden = true;
  $("#home").hidden = false; $("#tabs").hidden = true; $("#closeBtn").hidden = true; $("#projName").textContent = "";
  loadState();
}

// ============================================================ home
let appState = {};
async function loadState() {
  appState = await api("GET", "/api/state");
  drawHome();
  const u = appState.update || {};
  $("#update").hidden = !u.newer;
  if (u.newer) $("#updateText").textContent = t("update_new", { v: u.latest });
  return appState;
}
function drawHome() {
  if (!appState.app) return;
  $("#authorName").textContent = appState.author;
  $("#aboutLine").textContent = `SpeakSync ${appState.version} · ${t("free")}`;
  const rec = appState.recent || [];
  $("#recentCard").hidden = !rec.length;
  $("#recent").innerHTML = rec.map((r, i) => `<button data-i="${i}" ${r.ok ? "" : "disabled"}><b>${esc(r.name)}</b><span class="path">${esc(r.path)}</span>${r.ok ? "" : `<span class="bad">${esc(t("missing"))}</span>`}</button>`).join("");
  $$("#recent button").forEach(b => b.onclick = async () => {
    const r = await api("POST", "/api/project/open", { path: rec[+b.dataset.i].path });
    if (r.ok) setProject(r.project);
  });
}
// ---- new project dialog
let nv = null, folderTouched = false;
function setFolder(p) { $("#nFolder").textContent = p; $("#nFolder").title = p; }
function folderFor(name) { return `${appState.documents}\\${(name || "My video").replace(/[<>:"/\\|?*]+/g, " ").trim() || "My video"}`; }
$("#newBtn").onclick = () => {
  nv = null; folderTouched = false;
  $("#nVideo").textContent = t("no_video"); $("#nVideo").title = ""; $("#nFolder").title = ""; $("#nName").value = ""; $("#nScript").value = "";
  setFolder(folderFor("")); $("#nCreate").disabled = true; $("#newDlg").hidden = false;
};
$("#nVideoBtn").onclick = async () => {
  $("#nVideoBtn").disabled = true;
  const r = await api("POST", "/api/pick/video").finally(() => $("#nVideoBtn").disabled = false);
  if (!r.ok) return;
  nv = r;
  $("#nVideo").title = r.path;
  $("#nVideo").textContent = `${r.path.split(/[\/]/).pop()}   (${fmt(r.duration, false)}${r.width ? `, ${r.width}×${r.height}` : ""})`;
  if (!$("#nName").value) $("#nName").value = r.name;
  if (!folderTouched) setFolder(folderFor($("#nName").value));
  $("#nCreate").disabled = false;
};
$("#nName").oninput = () => { if (!folderTouched) setFolder(folderFor($("#nName").value)); };
$("#nFolderBtn").onclick = async () => {
  const r = await api("POST", "/api/pick/folder", { start: $("#nFolder").textContent });
  if (r.ok) { folderTouched = true; setFolder(r.path); }
};
$("#nCancel").onclick = () => $("#newDlg").hidden = true;
$("#nCreate").onclick = async () => {
  if (!nv) return;
  $("#nCreate").disabled = true;
  const r = await api("POST", "/api/project/create", { video: nv.path, name: $("#nName").value, folder: $("#nFolder").textContent, script: $("#nScript").value })
    .finally(() => $("#nCreate").disabled = false);
  if (r.ok) { $("#newDlg").hidden = true; setProject(r.project); appState.recent = null; }
};
$("#openBtn").onclick = async () => { const r = await api("POST", "/api/project/open", {}); if (r.ok) setProject(r.project); };

// ============================================================ saving parts
let saveT = 0, saving = null;
function sortParts() {
  const timed = state.parts.filter(p => p.start != null).sort((a, b) => a.start - b.start);
  state.parts = [...timed, ...state.parts.filter(p => p.start == null)];
}
function changed(redraw = true) {
  sortParts();
  if (redraw) { drawParts(); drawRecList(); }
  drawTimeline();
  clearTimeout(saveT); saveT = setTimeout(flushSave, 700);
}
async function flushSave() {
  clearTimeout(saveT); saveT = 0;
  if (!state.project) return;
  const body = { parts: state.parts.map(p => ({ id: p.id, start: p.start, end: p.end, text: p.text })) };
  saving = api("PUT", "/api/project/parts", body);
  const r = await saving; saving = null;
  if (r.ok) {
    state.project = r.project;
    state.takes = Object.fromEntries(r.project.parts.map(p => [p.id, p.take ? p.stamp : 0]));
  }
}

// ============================================================ 1. mark
let markOpen = null, playUntil = null, view = null, drag = null;
const DUR = () => (vid.duration && isFinite(vid.duration) ? vid.duration : P()?.duration || 1);
function markLabel() {
  $("#markLbl").textContent = markOpen == null ? t("mark_start") : t("mark_end", { t: fmt(markOpen) });
  $("#markBtn").classList.toggle("open", markOpen != null);
}
function pressMark() {
  const now = vid.currentTime;
  if (markOpen == null) { markOpen = now; markLabel(); drawTimeline(); return; }
  let s = Math.min(markOpen, now), e = Math.max(markOpen, now);
  if (e - s < 0.3) e = Math.min(DUR(), s + 1);
  markOpen = null; markLabel();
  let p = state.parts.find(x => x.id === state.sel && x.start == null) || state.parts.find(x => x.start == null);
  if (!p) { p = { id: newId(), start: null, end: null, text: "" }; state.parts.push(p); }
  p.start = +s.toFixed(2); p.end = +e.toFixed(2);
  const next = state.parts.find(x => x.start == null && x !== p);
  state.sel = next ? next.id : p.id;
  changed();
  toast(t("marked", { a: fmt(p.start), b: fmt(p.end) }), "ok");
}
$("#markBtn").onclick = pressMark;
$("#playBtn").onclick = () => { playUntil = null; vid.paused ? vid.play() : vid.pause(); };
$$("[data-step]").forEach(b => b.onclick = () => seek(vid.currentTime + parseFloat(b.dataset.step)));
$("#rate").onchange = () => vid.playbackRate = parseFloat($("#rate").value);
function seek(tm) { vid.currentTime = Math.max(0, Math.min(DUR(), tm)); drawTimeline(); }
vid.addEventListener("play", () => $("#playBtn").textContent = "❚❚");
vid.addEventListener("pause", () => $("#playBtn").textContent = "▶");
vid.addEventListener("loadedmetadata", () => { view = null; drawTimeline(); });

// ---- parts list
function drawParts() {
  if (!P() || state.tab !== "mark") return;
  const box = $("#parts");
  if (!state.parts.length) { box.innerHTML = `<div class="empty">${esc(t("no_parts"))}</div>`; return; }
  box.innerHTML = state.parts.map((p, i) => {
    const rec = state.takes[p.id];
    const times = p.start == null ? `<span class="notime">${esc(t("no_time"))}</span>` :
      `<span class="times"><input type="text" class="t" data-k="start" value="${fmt(p.start)}"> – <input type="text" class="t" data-k="end" value="${fmt(p.end)}"></span>`;
    return `<div class="part ${p.id === state.sel ? "sel" : ""}" data-id="${p.id}">
      <div class="ph"><span class="badge ${rec ? "rec" : ""}" title="${rec ? esc(t("recorded")) : ""}">${rec ? "✓ " : ""}${i + 1}</span>${times}<span class="grow"></span>
        ${p.start != null ? `<button data-a="play" title="${esc(t("play_part"))}">▶</button>` : ""}
        <button data-a="del" class="danger" title="${esc(t("delete"))}">✕</button></div>
      <textarea dir="auto" placeholder="${esc(t("text_ph"))}">${esc(p.text)}</textarea></div>`;
  }).join("");
  $$("#parts .part").forEach(el => {
    const p = state.parts.find(x => x.id === el.dataset.id);
    el.onclick = e => {
      if (e.target.closest("input,textarea,button")) { if (state.sel !== p.id) { state.sel = p.id; $$("#parts .part").forEach(x => x.classList.toggle("sel", x === el)); drawTimeline(); } return; }
      state.sel = p.id; drawParts(); if (p.start != null) seek(p.start);
    };
    el.querySelector("textarea").oninput = e => { p.text = e.target.value; changed(false); };
    el.querySelectorAll("input.t").forEach(inp => inp.onchange = () => {
      const v = parseT(inp.value);
      if (v == null || v > DUR() + 0.01) { inp.classList.add("bad"); return; }
      p[inp.dataset.k] = +v.toFixed(2);
      if (p.end - p.start < 0.2) { if (inp.dataset.k === "start") p.end = Math.min(DUR(), p.start + 0.5); else p.start = Math.max(0, p.end - 0.5); }
      changed();
    });
    el.querySelector('[data-a="play"]')?.addEventListener("click", () => { seek(p.start); playUntil = p.end; vid.play(); });
    el.querySelector('[data-a="del"]').onclick = () => {
      if (state.takes[p.id] && !confirm(t("del_rec_q"))) return;
      state.parts = state.parts.filter(x => x !== p); changed();
    };
  });
  $("#parts .sel")?.scrollIntoView({ block: "nearest" });
}
$("#addPartBtn").onclick = () => {
  const p = { id: newId(), start: null, end: null, text: "" };
  state.parts.push(p); state.sel = p.id; changed();
  setTimeout(() => $(`#parts [data-id="${p.id}"] textarea`)?.focus(), 30);
};
// ---- script menu
$("#scriptMenuBtn").onclick = e => { e.stopPropagation(); $("#scriptMenu").hidden = !$("#scriptMenu").hidden; };
document.addEventListener("click", () => $("#scriptMenu").hidden = true);
$("#scriptMenu").onclick = async e => {
  const a = e.target.closest("button")?.dataset.act; if (!a) return;
  $("#scriptMenu").hidden = true;
  await flushSave();
  if (a === "paste") { $("#pasteText").value = ""; $("#pasteReplace").checked = !state.parts.length; $("#pasteDlg").hidden = false; $("#pasteText").focus(); }
  if (a === "import") { const r = await api("POST", "/api/project/script", { replace: !state.parts.length }); if (r.ok) { setProject(r.project); toast(t("script_in", { n: r.count }), "ok"); } }
  if (a === "savetxt" || a === "savesrt") { const r = await api("POST", "/api/project/savescript", { kind: a === "savesrt" ? "srt" : "txt" }); if (r.ok) toast(t("saved_to", { p: r.path }), "ok"); }
  if (a === "clear" && confirm(t("clear_q"))) { state.parts = []; changed(); }
};
$("#pasteCancel").onclick = () => $("#pasteDlg").hidden = true;
$("#pasteOk").onclick = async () => {
  await flushSave();
  const r = await api("POST", "/api/project/script", { text: $("#pasteText").value, replace: $("#pasteReplace").checked });
  if (r.ok) { $("#pasteDlg").hidden = true; setProject(r.project); toast(t("script_in", { n: r.count }), "ok"); }
};

// ---- timeline (canvas)
const cv = $("#timeline");
function tlView() {
  const d = DUR();
  if (!view) view = [0, Math.min(d, 60)];                // start with one minute; the wheel zooms out
  view[1] = Math.min(view[1], d); if (view[1] - view[0] < 2) view[0] = Math.max(0, view[1] - 2);
  return view;
}
const xOf = (tm, w) => { const [a, b] = tlView(); return (tm - a) / (b - a) * w; };
const tOf = (x, w) => { const [a, b] = tlView(); return a + x / w * (b - a); };
function drawTimeline() {
  if (!P() || state.tab !== "mark") return;
  const dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (!W) return;
  if (cv.width !== W * dpr) { cv.width = W * dpr; cv.height = H * dpr; }
  const g = cv.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  const [a, b] = tlView(), span = b - a;
  // ruler
  const steps = [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  const st = steps.find(s => W / (span / s) >= 70) || 600;
  g.fillStyle = "#7d8a9c"; g.font = "11px Segoe UI"; g.strokeStyle = "#263142";
  for (let s = Math.ceil(a / st) * st; s <= b; s += st) {
    const x = xOf(s, W); g.beginPath(); g.moveTo(x + .5, 0); g.lineTo(x + .5, H); g.stroke();
    g.fillText(fmt(s, st < 1), x + 3, 12);
  }
  // parts
  state.parts.forEach((p, i) => {
    if (p.start == null) return;
    const x1 = xOf(p.start, W), x2 = xOf(p.end, W);
    if (x2 < 0 || x1 > W) return;
    const rec = state.takes[p.id], sel = p.id === state.sel;
    g.fillStyle = rec ? "rgba(46,204,113,.35)" : "rgba(76,141,255,.35)";
    g.strokeStyle = sel ? "#fff" : rec ? "#2ecc71" : "#4c8dff"; g.lineWidth = sel ? 2 : 1;
    g.beginPath(); g.roundRect(x1, 22, Math.max(2, x2 - x1), 50, 5); g.fill(); g.stroke();
    g.fillStyle = "#e9eef5"; g.font = "bold 12px Segoe UI";
    if (x2 - x1 > 16) g.fillText(String(i + 1), x1 + 5, 38);
    if (x2 - x1 > 50 && p.text) { g.font = "11px Tahoma"; g.fillStyle = "#c9d3df"; g.save(); g.beginPath(); g.rect(x1 + 4, 40, x2 - x1 - 8, 30); g.clip(); g.fillText(p.text.slice(0, 80), x1 + 5, 58); g.restore(); }
    g.fillStyle = sel ? "#fff" : "rgba(255,255,255,.5)"; g.fillRect(x1, 34, 3, 26); g.fillRect(x2 - 3, 34, 3, 26);
  });
  // open mark
  if (markOpen != null) {
    const x1 = xOf(Math.min(markOpen, vid.currentTime), W), x2 = xOf(Math.max(markOpen, vid.currentTime), W);
    g.fillStyle = "rgba(229,83,75,.4)"; g.fillRect(x1, 22, Math.max(2, x2 - x1), 50);
  }
  // play head
  const px = xOf(vid.currentTime, W);
  g.fillStyle = "#f5b942"; g.fillRect(px - 1, 0, 2, H);
  g.beginPath(); g.moveTo(px - 6, 0); g.lineTo(px + 6, 0); g.lineTo(px, 8); g.fill();
  // zoom bar
  if (span < DUR() - 0.01) { g.fillStyle = "#4c8dff"; g.fillRect(a / DUR() * W, H - 4, Math.max(4, span / DUR() * W), 3); }
  $("#timeNow").textContent = `${fmt(vid.currentTime)} / ${fmt(DUR())}`;
}
function hit(x) {
  const W = cv.clientWidth;
  for (const p of state.parts) {
    if (p.start == null) continue;
    const x1 = xOf(p.start, W), x2 = xOf(p.end, W);
    if (Math.abs(x - x1) <= 6) return { p, edge: "start" };
    if (Math.abs(x - x2) <= 6) return { p, edge: "end" };
  }
  for (const p of state.parts) if (p.start != null && x > xOf(p.start, W) && x < xOf(p.end, W)) return { p, edge: "move" };
  return null;
}
cv.addEventListener("pointerdown", e => {
  const W = cv.clientWidth, x = e.offsetX, h = hit(x);
  cv.setPointerCapture(e.pointerId);
  drag = { x0: x, t0: tOf(x, W), h, moved: false, orig: h ? { s: h.p.start, e: h.p.end } : null };
  if (h) { state.sel = h.p.id; drawParts(); } else seek(tOf(x, W));
});
cv.addEventListener("pointermove", e => {
  const W = cv.clientWidth, x = e.offsetX;
  if (!drag) { const h = hit(x); cv.style.cursor = h ? (h.edge === "move" ? "grab" : "ew-resize") : "crosshair"; return; }
  if (Math.abs(x - drag.x0) > 3) drag.moved = true;
  if (!drag.moved) return;
  const tm = Math.max(0, Math.min(DUR(), tOf(x, W)));
  const h = drag.h;
  if (!h) { seek(tm); return; }
  const p = h.p;
  if (h.edge === "start") { p.start = +Math.min(tm, p.end - 0.2).toFixed(2); seek(p.start); }
  else if (h.edge === "end") { p.end = +Math.max(tm, p.start + 0.2).toFixed(2); seek(p.end); }
  else {
    const len = drag.orig.e - drag.orig.s, d = tm - drag.t0;
    p.start = +Math.max(0, Math.min(DUR() - len, drag.orig.s + d)).toFixed(2); p.end = +(p.start + len).toFixed(2);
  }
  drawTimeline();
});
cv.addEventListener("pointerup", () => {
  if (drag?.h) { if (drag.moved) changed(); else if (drag.h.p.start != null) seek(drag.h.p.start); }
  drag = null;
});
cv.addEventListener("wheel", e => {
  e.preventDefault();
  const W = cv.clientWidth, [a, b] = tlView(), span = b - a, d = DUR();
  if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
    const sh = (e.deltaX || e.deltaY) / W * span; const na = Math.max(0, Math.min(d - span, a + sh)); view = [na, na + span];
  } else {
    const at = tOf(e.offsetX, W), f = e.deltaY > 0 ? 1.25 : 0.8, ns = Math.max(3, Math.min(d, span * f));
    let na = at - (at - a) * ns / span; na = Math.max(0, Math.min(d - ns, na)); view = [na, na + ns];
  }
  drawTimeline();
}, { passive: false });
window.addEventListener("resize", () => drawTimeline());

// ============================================================ 2. record
const LIGHT = {
  wait: () => [t("l_wait"), t("l_wait_s")], ready: n => [`${t("l_ready")}  ${n}`, t("l_ready_s")],
  speak: () => [t("l_speak"), t("l_speak_s")], fin: () => [t("l_finish"), t("l_finish_s")],
  hold: () => [t("l_hold"), t("l_hold_s")], saved: () => [t("l_saved"), t("l_saved_s")], done: () => [t("l_done"), t("l_done_s")],
};
let recIdx = -1, phase = "idle", stream = null, actx = null, analyser = null, recorder = null, chunks = [];
let noise = 0.004, spokeFor = 0, quietFor = 0, readyMode = "video", readyEnd = 0, endAt = 0, guideT = 0, recTimers = [], audioEl = null, micTried = false;
function setLight(kind, [big, small], timer = "") {
  $("#light").className = kind; $("#lightBig").textContent = big; $("#lightSmall").textContent = small; $("#lightTimer").textContent = timer;
}
function recStatus(msg, cls = "dim") { $("#recStatus").textContent = msg; $("#recStatus").className = cls; }
async function openMicOnce() { if (!micTried) { micTried = true; await openMic(); } }
async function openMic(deviceId) {
  try {
    if (stream) stream.getTracks().forEach(tr => tr.stop());
    stream = await navigator.mediaDevices.getUserMedia({ audio: { deviceId: deviceId ? { exact: deviceId } : undefined, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    actx = actx || new AudioContext();
    const src = actx.createMediaStreamSource(stream);
    analyser = actx.createAnalyser(); analyser.fftSize = 1024; src.connect(analyser);
    const devs = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "audioinput");
    const cur = stream.getAudioTracks()[0].getSettings().deviceId;
    $("#micSel").innerHTML = devs.map(d => `<option value="${esc(d.deviceId)}" ${d.deviceId === cur ? "selected" : ""}>${esc(d.label || t("microphone"))}</option>`).join("");
    recStatus(t("mic_ok"), "ok");
  } catch (e) { stream = null; recStatus(t("mic_bad") + " " + e.message, "bad"); }
}
$("#micSel").onchange = () => openMic($("#micSel").value);
const buf = new Float32Array(1024);
function level() { if (!analyser) return 0; analyser.getFloatTimeDomainData(buf); let s = 0; for (const v of buf) s += v * v; return Math.sqrt(s / buf.length); }

function timedParts() { return state.parts.filter(p => p.start != null); }
function drawRecList() {
  if (!P() || state.tab !== "record") return;
  const parts = state.parts;
  $("#recList").innerHTML = parts.map((p, i) => {
    const rec = state.takes[p.id];
    return `<button data-i="${i}" class="${i === recIdx ? "cur" : ""}" ${p.start == null ? "disabled" : ""}><span class="badge ${rec ? "rec" : ""}">${rec ? "✓" : i + 1}</span>
      <span class="tx">${esc(p.text || t("free_talk"))}</span><span class="tm">${p.start == null ? esc(t("no_time")) : fmt(p.start)}</span></button>`;
  }).join("") || `<div class="empty">${esc(t("no_parts_rec"))}</div>`;
  $$("#recList button").forEach(b => b.onclick = () => { stopRec(); recIdx = +b.dataset.i; drawRecList(); showRecPart(); });
  $("#recList .cur")?.scrollIntoView({ block: "nearest" });
  $$("#modeSeg button").forEach(b => b.classList.toggle("on", b.dataset.mode === P().mode));
}
function pickRecPart() {
  const parts = state.parts;
  if (recIdx < 0 || recIdx >= parts.length || parts[recIdx].start == null) {
    recIdx = parts.findIndex(p => p.start != null && !state.takes[p.id]);
    if (recIdx < 0) recIdx = parts.findIndex(p => p.start != null);
  }
  drawRecList(); showRecPart();
}
function showRecPart() {
  if (!P() || state.tab !== "record" || phase !== "idle") return;
  const p = state.parts[recIdx];
  $("#timebarFill").style.width = "100%"; $("#timebarFill").style.background = "var(--green)";
  if (!p) {
    $("#readerHead").textContent = ""; $("#readText").textContent = timedParts().length ? "" : t("no_parts_rec");
    $("#nextText").textContent = ""; setLight("wait", LIGHT.wait()); $("#goBtn").disabled = true; return;
  }
  $("#goBtn").disabled = false;
  const n = state.parts.indexOf(p) + 1, len = p.end - p.start;
  $("#readerHead").textContent = `${n} / ${state.parts.length}   ·   ${fmt(p.start)} – ${fmt(p.end)}   (${len.toFixed(1)} s)`;
  const words = (p.text || "").split(/\s+/).filter(Boolean);
  $("#readText").className = words.length ? "" : "free";
  $("#readText").innerHTML = words.length ? words.map(w => `<span>${esc(w)}</span>`).join(" ") : esc(t("free_talk_long"));
  const nx = state.parts[recIdx + 1];
  $("#nextText").textContent = nx ? `▼ ${nx.text || t("free_talk")}` : "";
  $("#reader").scrollTop = 0;
  $("#listenBtn").disabled = !state.takes[p.id];
  $("#goBtn").innerHTML = `<kbd>Space</kbd> ${esc(state.takes[p.id] ? t("k_again") : t("k_start"))}`;
  setLight("wait", state.takes[p.id] ? [t("l_wait"), t("l_recorded_s")] : LIGHT.wait());
  if (vid.readyState >= 1) { vid.pause(); vid.currentTime = p.start; }
}
function later(fn, ms) { recTimers.push(setTimeout(fn, ms)); }
function startRec() {
  const p = state.parts[recIdx];
  if (!p || p.start == null) return toast(t("need_mark"), "bad");
  if (!stream) { openMic(); return toast(t("mic_bad"), "bad"); }
  if (!P().video_ok) return toast(t("video_missing"), "bad");
  if (actx.state === "suspended") actx.resume();
  stopRec(true);
  vid.muted = !$("#hearChk").checked; vid.playbackRate = 1;
  const pre = Math.min(3, p.start);
  phase = "ready"; noise = 0.004;
  if (pre >= 0.8) { readyMode = "video"; vid.currentTime = p.start - pre; vid.play().catch(() => {}); }
  else { readyMode = "timer"; vid.pause(); vid.currentTime = p.start; readyEnd = performance.now() + 3000; }
  $("#readText").classList.remove("on");
  $("#goBtn").innerHTML = `<kbd>Esc</kbd> ${esc(t("k_stop"))}`;
}
function beginSpeak() {
  const p = state.parts[recIdx];
  phase = "speak"; spokeFor = 0; quietFor = 0; endAt = 0; chunks = [];
  const mime = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm"].find(m => MediaRecorder.isTypeSupported(m)) || "";
  recorder = new MediaRecorder(stream, mime ? { mimeType: mime, audioBitsPerSecond: 128000 } : {});
  recorder.ondataavailable = e => e.data.size && chunks.push(e.data);
  recorder.start(250);
  if (readyMode === "timer") vid.play().catch(() => {});
  $("#readText").classList.add("on");
  setLight("speak", LIGHT.speak());
  $("#goBtn").innerHTML = `<kbd>Space</kbd> ${esc(t("k_done"))}`;
  startGuide(p);
}
function startGuide(p) {
  const spans = [...$("#readText").children];
  if (!$("#guideChk").checked || !spans.length) return;
  const ms = Math.max(180, Math.min(900, (p.end - p.start) * 1000 / spans.length));   // the part's own speed
  let i = 0;
  const step = () => {
    if (phase !== "speak") return;
    spans.forEach((s, k) => s.className = k < i ? "past" : k === i ? "now" : "");
    const el = spans[Math.min(i, spans.length - 1)], box = $("#reader");
    const top = el.offsetTop - box.offsetTop;
    if (top > box.scrollTop + box.clientHeight * 0.55 || top < box.scrollTop) box.scrollTop = top - box.clientHeight * 0.3;
    if (i < spans.length) i++;
  };
  step(); guideT = setInterval(step, ms);
}
let lastTick = performance.now();
function tick() {
  const now = performance.now(), dt = (now - lastTick) / 1000; lastTick = now;
  if (state.tab === "mark" && P()) {
    if (playUntil != null && vid.currentTime >= playUntil) { vid.pause(); playUntil = null; }
    if (!vid.paused || markOpen != null) {
      const [a, b] = tlView(), tm = vid.currentTime;
      if (tm > b || tm < a) { const sp = b - a, na = Math.max(0, Math.min(DUR() - sp, tm - sp * 0.1)); view = [na, na + sp]; }
      drawTimeline();
    }
  }
  if (state.tab !== "record") return;
  const lv = level();
  $("#meter").style.width = Math.min(100, lv * 900) + "%";
  const p = state.parts[recIdx];
  if (!p) return;
  if (phase === "ready") {
    noise = noise * 0.9 + lv * 0.1;
    const left = readyMode === "video" ? p.start - vid.currentTime : (readyEnd - now) / 1000;
    setLight("ready", LIGHT.ready(Math.max(1, Math.ceil(left - 0.05))));
    if (left <= 0.04) beginSpeak();
    return;
  }
  if (phase !== "speak") return;
  const loud = lv > Math.max(0.012, noise * 3.5);
  if (loud) { spokeFor += dt; quietFor = 0; } else quietFor += dt;
  const len = p.end - p.start, vt = vid.currentTime, left = p.end - vt;
  const fill = $("#timebarFill");
  fill.style.width = Math.max(0, Math.min(100, left / len * 100)) + "%";
  fill.style.background = left > 2 ? "var(--green)" : "var(--amber)";
  $("#lightTimer").textContent = left >= 0 ? fmt(Math.ceil(left), false) : "+" + (-left).toFixed(1);
  const mode = P().mode;
  if (left <= 0.03 || vid.ended) {
    if (!endAt) endAt = now;
    if (mode === "wait") { if (!vid.paused) vid.pause(); setLight("late", LIGHT.hold(), "+" + ((now - endAt) / 1000).toFixed(1)); }
    else setLight("late", LIGHT.fin(), "+" + ((now - endAt) / 1000).toFixed(1));
    fill.style.width = "100%"; fill.style.background = "var(--red)";
    if (quietFor >= (mode === "wait" ? 1.2 : 0.7)) return finishRec();
    if (mode === "fit" && now - endAt > 6000) return finishRec();
  } else if (spokeFor > 1 && quietFor >= 3) {
    return finishRec();                        // finished early
  }
}
function finishRec() {
  if (phase !== "speak") return;
  phase = "saving"; clearInterval(guideT);
  vid.pause();
  [...$("#readText").children].forEach(s => s.className = "");
  $("#readText").classList.remove("on");
  setLight("wait", LIGHT.saved());
  const p = state.parts[recIdx], spoke = spokeFor;
  recorder.onstop = async () => {
    const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
    try {
      await flushSave();
      const r = await fetch(`/api/take/${p.id}`, { method: "PUT", headers: { "X-Key": KEY, "Content-Type": blob.type }, body: blob }).then(x => x.json());
      if (!r.ok) throw new Error(r.error || "save failed");
      state.project = r.project; state.takes = Object.fromEntries(r.project.parts.map(x => [x.id, x.take ? x.stamp : 0]));
      recStatus(spoke < 0.8 ? t("rec_quiet", { n: recIdx + 1 }) : t("rec_saved", { n: recIdx + 1 }), spoke < 0.8 ? "bad" : "ok");
    } catch (e) { phase = "idle"; recStatus(t("rec_not_saved") + " " + e.message, "bad"); showRecPart(); return; }
    let next = state.parts.findIndex((x, k) => k > recIdx && x.start != null && !state.takes[x.id]);
    if (next < 0) next = state.parts.findIndex(x => x.start != null && !state.takes[x.id]);
    drawRecList(); drawMake();
    if (next < 0) { phase = "idle"; showRecPart(); setLight("wait", LIGHT.done()); return; }
    phase = "rest"; setLight("wait", LIGHT.saved());
    later(() => { recIdx = next; phase = "idle"; drawRecList(); showRecPart(); if ($("#autoChk").checked) later(startRec, 900); }, 1200);
  };
  recorder.stop();
}
function stopRec(quiet) {
  recTimers.forEach(clearTimeout); recTimers = []; clearInterval(guideT);
  if (audioEl) { audioEl.pause(); audioEl = null; }
  if (recorder && recorder.state !== "inactive" && phase !== "saving") { recorder.onstop = null; recorder.stop(); }
  if (phase !== "saving") phase = "idle";
  vid.pause();
  if (!quiet) showRecPart();
}
function listen() {
  const p = state.parts[recIdx]; if (!p || !state.takes[p.id] || phase !== "idle") return;
  stopRec(true);
  audioEl = new Audio(media(`/media/take/${p.id}`, state.takes[p.id]));
  vid.muted = !$("#hearChk").checked; vid.currentTime = p.start;
  audioEl.onplay = () => vid.play().catch(() => {});
  audioEl.onended = () => { vid.pause(); audioEl = null; };
  audioEl.play();
}
function moveRec(d) {
  stopRec(true);
  let i = recIdx;
  do { i += d; } while (i >= 0 && i < state.parts.length && state.parts[i].start == null);
  if (i >= 0 && i < state.parts.length) recIdx = i;
  drawRecList(); showRecPart();
}
$("#goBtn").onclick = () => phase === "speak" ? finishRec() : phase === "ready" ? stopRec() : startRec();
$("#redoBtn").onclick = () => { stopRec(true); startRec(); };
$("#listenBtn").onclick = listen;
$("#backBtn").onclick = () => moveRec(-1);
$("#fwdBtn").onclick = () => moveRec(1);
$("#pauseBtn").onclick = () => stopRec();
$("#hearChk").onchange = () => { vid.muted = !$("#hearChk").checked; };
$("#modeSeg").onclick = e => { const b = e.target.closest("button"); if (b) setSetting({ mode: b.dataset.mode }); };

// ============================================================ 3. make video
let setT = 0;
async function setSetting(obj) {
  Object.assign(P(), obj); drawMake(); drawRecList();
  clearTimeout(setT);
  setT = setTimeout(async () => { const r = await api("POST", "/api/project/settings", obj); if (r.ok) { state.project = r.project; } }, 250);
}
function drawMake() {
  if (!P() || state.tab !== "make") return;
  const pr = P(), timed = timedParts(), recd = timed.filter(p => state.takes[p.id]), untimed = state.parts.filter(p => p.start == null);
  $("#mkSummary").innerHTML = `<p>${esc(t("mk_count", { a: recd.length, b: timed.length }))}</p>` +
    (untimed.length ? `<p class="warn">${esc(t("mk_untimed", { n: untimed.length }))}</p>` : "");
  const miss = timed.filter(p => !state.takes[p.id]);
  $("#missing").innerHTML = miss.length ? `<span class="dim">${esc(t("mk_missing"))}</span> ` + miss.map(p => `<button data-id="${p.id}">${state.parts.indexOf(p) + 1} · ${fmt(p.start)}</button>`).join("") : "";
  $$("#missing button").forEach(b => b.onclick = () => { recIdx = state.parts.findIndex(x => x.id === b.dataset.id); showTab("record"); });
  $$("#modeChoice label").forEach(l => { l.classList.toggle("on", l.dataset.mode === pr.mode); l.querySelector("input").checked = l.dataset.mode === pr.mode; });
  $("#bgVol").value = Math.round(pr.bg_volume * 100); $("#bgVolTxt").textContent = pr.bg_volume > 0 ? Math.round(pr.bg_volume * 100) + "%" : t("off");
  $("#duckChk").checked = pr.duck; $("#duckChk").disabled = pr.bg_volume <= 0;
  $("#voiceVol").value = Math.round(pr.voice_volume * 100); $("#voiceVolTxt").textContent = Math.round(pr.voice_volume * 100) + "%";
  $("#speedChk").checked = pr.speed_fit; $("#speedRow").hidden = pr.mode !== "fit";
  if (!exporting) $("#makeBtn").disabled = !recd.length;
}
$("#modeChoice").onchange = e => setSetting({ mode: e.target.value });
$("#bgVol").oninput = () => setSetting({ bg_volume: $("#bgVol").value / 100 });
$("#voiceVol").oninput = () => setSetting({ voice_volume: $("#voiceVol").value / 100 });
$("#duckChk").onchange = () => setSetting({ duck: $("#duckChk").checked });
$("#speedChk").onchange = () => setSetting({ speed_fit: $("#speedChk").checked });
let exporting = false, pollT = 0;
$("#makeBtn").onclick = async () => {
  await flushSave(); clearTimeout(setT);
  const pr = P(); await api("POST", "/api/project/settings", { mode: pr.mode, bg_volume: pr.bg_volume, duck: pr.duck, voice_volume: pr.voice_volume, speed_fit: pr.speed_fit });
  $("#makeBtn").disabled = true;
  const r = await api("POST", "/api/export", {});
  if (!r.ok) { $("#makeBtn").disabled = false; return; }
  $("#mkResult").innerHTML = ""; pollExport();
};
$("#cancelBtn").onclick = () => api("POST", "/api/export/cancel");
async function pollExport() {
  clearTimeout(pollT);
  const s = await api("GET", "/api/export");
  exporting = !!s.running;
  $("#cancelBtn").hidden = !s.running; $("#progress").hidden = !s.running && s.stage !== "done";
  $("#makeBtn").disabled = s.running;
  if (s.running) {
    $("#progressFill").style.width = (s.pct || 0) + "%";
    $("#mkStage").textContent = `${t("st_" + s.stage)} · ${Math.round(s.pct || 0)}%`;
    pollT = setTimeout(pollExport, 700); return;
  }
  if (s.stage === "done") {
    $("#progressFill").style.width = "100%"; $("#mkStage").textContent = "";
    $("#mkResult").innerHTML = `<p class="ok">✔ ${esc(t("mk_done"))}</p><p class="dim">${esc(s.out)}<br>${esc(t("mk_srt"))}</p>
      <div class="row"><button class="primary" id="playOut">▶ ${esc(t("mk_play"))}</button><button id="showOut">${esc(t("mk_folder"))}</button></div>` +
      (s.warnings?.length ? `<ul class="warns">${s.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : "");
    $("#playOut").onclick = () => api("POST", "/api/open", { what: "output" });
    $("#showOut").onclick = () => api("POST", "/api/open", { what: "output_folder" });
  } else if (s.stage === "error") {
    $("#mkStage").textContent = "";
    $("#mkResult").innerHTML = s.error === "cancelled" ? `<p class="dim">${esc(t("mk_cancelled"))}</p>` : `<p class="bad">${esc(t("mk_failed"))} ${esc(s.error)}</p>`;
  }
  drawMake();
}

// ============================================================ keys
document.addEventListener("keydown", e => {
  if (!$("#newDlg").hidden || !$("#pasteDlg").hidden) { if (e.key === "Escape") { $("#newDlg").hidden = true; $("#pasteDlg").hidden = true; } return; }
  if (!$("#helpDlg").hidden) { if (e.key === "Escape") $("#helpDlg").hidden = true; return; }
  if (e.target.closest("input[type=text],textarea,select") || e.ctrlKey || e.altKey || e.metaKey || !P()) return;
  const k = e.key.toLowerCase();
  if (state.tab === "mark") {
    if (k === "m") { e.preventDefault(); pressMark(); }
    else if (k === " " || k === "k") { e.preventDefault(); $("#playBtn").click(); }
    else if (k === "arrowleft") { e.preventDefault(); seek(vid.currentTime - (e.shiftKey ? 0.1 : 1)); }
    else if (k === "arrowright") { e.preventDefault(); seek(vid.currentTime + (e.shiftKey ? 0.1 : 1)); }
    else if (k === "escape" && markOpen != null) { markOpen = null; markLabel(); drawTimeline(); }
  } else if (state.tab === "record") {
    if (k === " " || k === "enter") { e.preventDefault(); $("#goBtn").click(); }
    else if (k === "r") $("#redoBtn").click();
    else if (k === "l") listen();
    else if (k === "arrowup") { e.preventDefault(); moveRec(-1); }
    else if (k === "arrowdown") { e.preventDefault(); moveRec(1); }
    else if (k === "escape") stopRec();
  }
});

// ============================================================ top bar, help, about, updates
$$("#tabs button").forEach(b => b.onclick = () => showTab(b.dataset.tab));
$("#closeBtn").onclick = closeProject;
$("#uiLang").onchange = async () => { await loadLang($("#uiLang").value); api("POST", "/api/ui", { lang: uiLang }); };
$("#helpBtn").onclick = () => { $("#helpBox").innerHTML = t("help_html") + `<div class="row"><span class="grow"></span><button class="primary" id="helpOk">OK</button></div>`; $("#helpDlg").hidden = false; $("#helpOk").onclick = () => $("#helpDlg").hidden = true; };
$("#aboutLink").onclick = () => {
  $("#helpBox").innerHTML = `<div class="about-head"><img src="/static/icon.svg" alt=""><div><h2>SpeakSync ${esc(appState.version)}</h2>
    <div class="dim">${esc(t("made_by"))} <b style="color:var(--text)">${esc(appState.author)}</b> · ${esc(t("free"))}</div></div></div>
    <p>${esc(t("about_p"))}</p>
    <div class="about-links"><button class="linkbtn li" id="liBtn"><span class="ico">in</span>${esc(t("linkedin"))}</button><button class="linkbtn" id="hp">${esc(t("source_code"))}</button>
    <span class="dim small" style="direction:ltr">${esc(appState.homepage.replace("https://", ""))}</span></div>
    <p id="updLine" class="dim"></p>
    <div class="row"><button id="chkUpd">${esc(t("check_updates"))}</button><span class="grow"></span><button class="primary" id="helpOk">OK</button></div>`;
  $("#helpDlg").hidden = false;
  $("#helpOk").onclick = () => $("#helpDlg").hidden = true;
  $("#hp").onclick = () => api("POST", "/api/open", { what: "homepage" });
  $("#liBtn").onclick = () => api("POST", "/api/open", { what: "linkedin" });
  $("#chkUpd").onclick = async () => {
    $("#updLine").textContent = "…";
    const u = await api("GET", "/api/update");
    appState.update = u;
    $("#updLine").textContent = !u.ok ? t("upd_fail") : u.newer ? t("update_new", { v: u.latest }) : t("upd_none");
    $("#update").hidden = !u.newer; if (u.newer) $("#updateText").textContent = t("update_new", { v: u.latest });
  };
};
$("#updateBtn").onclick = () => api("POST", "/api/open", { what: "update" });
$("#linkedinBtn").onclick = () => api("POST", "/api/open", { what: "linkedin" });
$("#githubBtn").onclick = () => api("POST", "/api/open", { what: "homepage" });
$("#helpDlg").onclick = e => { if (e.target.id === "helpDlg") $("#helpDlg").hidden = true; };

// "I am still here" - when the window closes, the program stops by itself
setInterval(() => api("POST", "/api/ping").catch(() => {}), 20000);
window.addEventListener("beforeunload", () => navigator.sendBeacon(`/api/bye?k=${encodeURIComponent(KEY)}`));

(async () => {
  await loadState();
  const want = appState.ui_lang || (navigator.language || "en").slice(0, 2);
  await loadLang(["en", "fa"].includes(want) ? want : "en");
  if (appState.project) setProject(appState.project);
  setInterval(tick, 50);
})();
