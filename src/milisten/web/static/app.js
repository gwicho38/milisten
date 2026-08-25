"use strict";
/* milisten frontend — vanilla JS, no build step, zero external network requests. */

// ----------------------------------------------------------------------------
// Session token: captured from ?token= on load (or sessionStorage on refresh),
// sent on every API call, then stripped from the visible URL so it does not
// linger in history or leak through Referer.
// ----------------------------------------------------------------------------
const TOKEN_KEY = "milisten.sessionToken";
const TOKEN_HEADER = "X-Milisten-Token";
const _urlToken = new URLSearchParams(location.search).get("token") || "";
let _stored = "";
try { _stored = sessionStorage.getItem(TOKEN_KEY) || ""; } catch { /* best-effort */ }
const TOKEN = _urlToken || _stored;
if (_urlToken) {
  try { sessionStorage.setItem(TOKEN_KEY, _urlToken); } catch { /* best-effort */ }
  if (window.history && history.replaceState) {
    const u = new URL(location.href);
    u.searchParams.delete("token");
    history.replaceState(null, "", u.pathname + u.search + u.hash);
  }
}

// ----------------------------------------------------------------------------
// State
// ----------------------------------------------------------------------------
const State = {
  areas: [],
  orphans: [],
  voices: [],
  audioDir: "",
  selected: null,
  live: null,
  poll: null,
  build: { engine: "kokoro", voice: "heart", speed: 1.0, layout: false },
  playing: { area: null, chapter: -1 },
};

const $ = (id) => document.getElementById(id);

// ----------------------------------------------------------------------------
// API client. Parses {error,hint} into a thrown ApiError.
// ----------------------------------------------------------------------------
class ApiError extends Error {
  constructor(status, error, hint) {
    super(error || `HTTP ${status}`);
    this.status = status;
    this.hint = hint || "";
  }
}

async function api(method, path, body) {
  const headers = { [TOKEN_HEADER]: TOKEN };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* non-JSON body */ }
  if (!res.ok) {
    const detail = data && typeof data === "object" ? data : {};
    throw new ApiError(res.status, detail.error || text.slice(0, 200), detail.hint);
  }
  return data;
}

// ----------------------------------------------------------------------------
// Formatting + DOM helpers
// ----------------------------------------------------------------------------
function clock(seconds) {
  const s = Math.max(0, Math.round(seconds || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

function longDuration(seconds) {
  const mins = Math.round((seconds || 0) / 60);
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
}

function megabytes(bytes) {
  return `${(bytes / 1e6).toFixed(0)} MB`;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function toast(message, kind = "success", ms = 4200) {
  const node = document.createElement("div");
  node.className = `toast toast-${kind}`;
  node.textContent = message;
  $("toast-stack").append(node);
  setTimeout(() => node.remove(), ms);
  $("aria-live").textContent = message;
}

function reportError(exc, fallback) {
  const hint = exc instanceof ApiError && exc.hint ? ` — ${exc.hint}` : "";
  toast(`${exc.message || fallback}${hint}`, "error", 7000);
}

function closeModal() {
  $("modal-root").hidden = true;
  $("modal-root").innerHTML = "";
}

function openModal(title, bodyHtml, footHtml = "") {
  const root = $("modal-root");
  root.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <div class="modal-head">
        <h2 class="modal-title">${esc(title)}</h2>
        <button class="btn btn-sm" data-close>Close</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
      ${footHtml ? `<div class="modal-foot">${footHtml}</div>` : ""}
    </div>`;
  root.hidden = false;
  root.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", closeModal));
  root.addEventListener("click", (e) => { if (e.target === root) closeModal(); });
}

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("modal-root").hidden) closeModal();
});

// ----------------------------------------------------------------------------
// Theme
// ----------------------------------------------------------------------------
const THEME_KEY = "milisten.theme";
function applyTheme(theme) {
  if (theme === "light") document.documentElement.setAttribute("data-theme", "light");
  else document.documentElement.removeAttribute("data-theme");
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* best-effort */ }
}
(function initTheme() {
  let saved = "dark";
  try { saved = localStorage.getItem(THEME_KEY) || "dark"; } catch { /* best-effort */ }
  applyTheme(saved);
})();

// ----------------------------------------------------------------------------
// Rendering — sidebar
// ----------------------------------------------------------------------------
function areaByName(name) {
  return State.areas.find((a) => a.name === name) || null;
}

function renderSidebar() {
  const list = $("area-list");
  const sourceCount = State.areas.reduce((n, a) => n + a.sources.length, 0);
  $("area-counter").textContent = `${State.areas.length} · ${sourceCount} src`;

  const rows = State.areas.map((area) => {
    const rec = area.recording;
    const live = State.live && State.live.area === area.name;
    const badge = live
      ? `<span class="pill pill-live"><span class="spinner"></span> building</span>`
      : rec
        ? `<span class="pill pill-audio">${longDuration(rec.seconds)}</span>`
        : `<span class="pill pill-none">no audio</span>`;
    return `
      <button class="area-row" role="listitem" data-area="${esc(area.name)}"
              aria-current="${State.selected === area.name}">
        <span class="area-row-top">
          <span class="area-name">${esc(area.name)}</span>
          <span class="counter">${area.sources.length}</span>
        </span>
        <span class="area-meta">${badge}</span>
      </button>`;
  });

  const orphans = State.orphans.map((rec) => `
      <button class="area-row" role="listitem" data-area="${esc(rec.area)}"
              aria-current="${State.selected === rec.area}">
        <span class="area-row-top">
          <span class="area-name">${esc(rec.area)}</span>
          <span class="counter">—</span>
        </span>
        <span class="area-meta">
          <span class="pill pill-audio">${longDuration(rec.seconds)}</span>
          <span class="pill">queue empty</span>
        </span>
      </button>`);

  list.innerHTML = rows.concat(orphans).join("") ||
    `<div class="field-hint" style="padding:0.5rem">Queue is empty. Add a source below.</div>`;
  list.querySelectorAll("[data-area]").forEach((btn) =>
    btn.addEventListener("click", () => select(btn.dataset.area)));

  $("area-options").innerHTML = State.areas
    .map((a) => `<option value="${esc(a.name)}"></option>`).join("");
}

// ----------------------------------------------------------------------------
// Rendering — panel
// ----------------------------------------------------------------------------
function sourcesCard(area) {
  if (!area || !area.sources.length) {
    return `<div class="card"><div class="field-hint">No queued sources in this area.</div></div>`;
  }
  const rows = area.sources.map((s) => `
    <tr>
      <td>
        <span class="src-title">${esc(s.title)}</span>
        <span class="src-ref">${esc(s.ref)}</span>
      </td>
      <td><span class="pill">${esc(s.isLocal ? "file" : s.kind)}</span></td>
      <td class="src-actions">
        <button class="btn btn-sm" data-preview="${esc(s.ref)}">Preview</button>
        <button class="btn btn-sm btn-danger" data-remove="${esc(s.ref)}">Remove</button>
      </td>
    </tr>`);
  return `
    <div class="card">
      <h3 class="card-title">Queued sources (${area.sources.length})</h3>
      <table class="src-table">
        <thead><tr><th>Source</th><th>Type</th><th></th></tr></thead>
        <tbody>${rows.join("")}</tbody>
      </table>
    </div>`;
}

function buildCard(area) {
  const live = State.live && State.live.area === area.name ? State.live : null;
  const busy = Boolean(State.live);
  const voices = State.voices
    .map((v) => `<option value="${esc(v)}" ${v === State.build.voice ? "selected" : ""}>${esc(v)}</option>`)
    .join("");

  let progress = "";
  if (live) {
    const pct = live.chaptersTotal ? (live.chaptersDone / live.chaptersTotal) * 100 : 4;
    const log = live.events.slice().reverse().map((e) => `
      <div class="log-row log-${esc(e.kind)}">
        <span class="log-t">${clock(e.t)}</span><span>${esc(e.text)}</span>
      </div>`).join("");
    progress = `
      <div class="progress-track"><div class="progress-fill" style="width:${pct.toFixed(1)}%"></div></div>
      <div class="progress-note">
        <span><span class="spinner"></span> ${esc(live.message || "starting")}</span>
        <span>${live.chaptersDone}/${live.chaptersTotal} · ${longDuration(live.seconds)} rendered · ${clock(live.elapsed)} elapsed</span>
      </div>
      <div class="log">${log}</div>`;
  }

  return `
    <div class="card">
      <h3 class="card-title">Render</h3>
      <div class="build-row">
        <div class="field">
          <label for="engine-select">Engine</label>
          <select id="engine-select" class="field-narrow">
            <option value="kokoro" ${State.build.engine === "kokoro" ? "selected" : ""}>kokoro</option>
            <option value="say" ${State.build.engine === "say" ? "selected" : ""}>say</option>
          </select>
        </div>
        <div class="field">
          <label for="voice-select">Voice</label>
          <select id="voice-select" class="field-narrow">${voices}</select>
        </div>
        <div class="field">
          <label for="speed-input">Speed</label>
          <input id="speed-input" class="field-narrow" type="number" min="0.5" max="2" step="0.05"
                 value="${State.build.speed}" />
        </div>
        <div class="field">
          <label for="layout-check">PDF layout</label>
          <label class="field-hint"><input id="layout-check" type="checkbox"
            ${State.build.layout ? "checked" : ""} /> keep columns</label>
        </div>
        ${live
          ? `<button class="btn btn-danger" id="cancel-btn">Cancel build</button>`
          : `<button class="btn btn-primary" id="build-btn" ${busy || !area.sources.length ? "disabled" : ""}>
               ${area.recording ? "Rebuild" : "Build"} ${esc(area.name)}
             </button>`}
      </div>
      ${busy && !live ? `<div class="field-hint" style="margin-top:0.5rem">Another area is rendering; one build runs at a time.</div>` : ""}
      ${progress}
    </div>`;
}

function playerCard(rec) {
  if (!rec) return "";
  const chapters = rec.chapters.length
    ? rec.chapters.map((c, i) => `
        <button class="chapter-row" data-seek="${c.start}" data-idx="${i}"
                aria-current="${State.playing.area === rec.area && State.playing.chapter === i}">
          <span class="chapter-idx">${i + 1}</span>
          <span class="chapter-title">${esc(c.title)}</span>
          <span class="chapter-time">${clock(c.start)} · ${longDuration(c.end - c.start)}</span>
        </button>`).join("")
    : `<div class="field-hint">No chapter manifest for this recording.</div>`;

  const src = `/audio/${encodeURIComponent(rec.area)}.m4b?v=${Math.floor(rec.modified)}`;
  return `
    <div class="card player">
      <h3 class="card-title">Recording · ${longDuration(rec.seconds)} · ${megabytes(rec.bytes)}${
        rec.voice ? ` · ${esc(rec.engine)}/${esc(rec.voice)}` : ""}</h3>
      <audio id="player" controls preload="metadata" src="${src}"></audio>
      <div class="chapter-list">${chapters}</div>
      <div class="modal-foot" style="padding:0.75rem 0 0">
        <span class="field-hint">
          Chapter marks are in the file too — Apple Books and Plex read them.
          <a href="${src}" target="_blank" rel="noopener">Open in a new tab</a> if the player above misbehaves.
        </span>
        <button class="btn btn-sm btn-danger" id="delete-rec">Delete recording</button>
      </div>
    </div>`;
}

function renderPanel() {
  const panel = $("panel");
  const area = areaByName(State.selected);
  const rec = area ? area.recording : State.orphans.find((r) => r.area === State.selected);

  if (!area && !rec) {
    panel.innerHTML = `
      <div class="panel-empty">
        <h2 class="panel-title">Pick an area</h2>
        <p class="panel-sub">Each area renders to one <code>.m4b</code>, one chapter per source.
        Audio lands in <code>${esc(State.audioDir)}</code>.</p>
      </div>`;
    return;
  }

  const sourceCount = area ? area.sources.length : 0;
  const estimate = area && sourceCount
    ? `${sourceCount} source${sourceCount === 1 ? "" : "s"} queued`
    : "no queued sources";

  panel.innerHTML = `
    <div class="panel-head">
      <div>
        <h2 class="panel-title">${esc(State.selected)}</h2>
        <div class="panel-sub">${estimate}${rec ? ` · ${longDuration(rec.seconds)} rendered` : ""}</div>
      </div>
    </div>
    ${area ? buildCard(area) : ""}
    ${playerCard(rec)}
    ${area ? sourcesCard(area) : ""}`;

  wirePanel(area, rec);
}

function wirePanel(area, rec) {
  const panel = $("panel");

  panel.querySelectorAll("[data-preview]").forEach((b) =>
    b.addEventListener("click", () => showPreview(b.dataset.preview)));
  panel.querySelectorAll("[data-remove]").forEach((b) =>
    b.addEventListener("click", () => removeSource(b.dataset.remove)));

  const engine = $("engine-select");
  if (engine) engine.addEventListener("change", () => { State.build.engine = engine.value; });
  const voice = $("voice-select");
  if (voice) voice.addEventListener("change", () => { State.build.voice = voice.value; });
  const speed = $("speed-input");
  if (speed) speed.addEventListener("change", () => {
    State.build.speed = Math.min(2, Math.max(0.5, Number(speed.value) || 1));
  });
  const layout = $("layout-check");
  if (layout) layout.addEventListener("change", () => { State.build.layout = layout.checked; });

  const buildBtn = $("build-btn");
  if (buildBtn) buildBtn.addEventListener("click", () => startBuild(area.name));
  const cancelBtn = $("cancel-btn");
  if (cancelBtn) cancelBtn.addEventListener("click", cancelBuild);
  const del = $("delete-rec");
  if (del) del.addEventListener("click", () => deleteRecording(rec.area));

  const audio = $("player");
  if (!audio || !rec) return;
  panel.querySelectorAll("[data-seek]").forEach((b) =>
    b.addEventListener("click", () => {
      audio.currentTime = Number(b.dataset.seek) + 0.05;
      audio.play().catch(() => { /* autoplay policy — the control is right there */ });
    }));
  audio.addEventListener("timeupdate", () => {
    const idx = rec.chapters.findLastIndex((c) => audio.currentTime >= c.start);
    if (idx === State.playing.chapter && State.playing.area === rec.area) return;
    State.playing = { area: rec.area, chapter: idx };
    panel.querySelectorAll("[data-idx]").forEach((b) =>
      b.setAttribute("aria-current", String(Number(b.dataset.idx) === idx)));
  });
}

// ----------------------------------------------------------------------------
// Actions
// ----------------------------------------------------------------------------
function select(name) {
  State.selected = name;
  renderSidebar();
  renderPanel();
}

function applyLibrary(data) {
  State.areas = data.areas;
  State.orphans = data.orphans;
  State.voices = data.voices;
  State.audioDir = data.audioDir;
  if (!State.selected || !(areaByName(State.selected) || State.orphans.some((r) => r.area === State.selected))) {
    State.selected = data.areas.length ? data.areas[0].name : (data.orphans[0] || {}).area || null;
  }
  renderSidebar();
  renderPanel();
}

async function refresh() {
  try {
    applyLibrary(await api("GET", "/api/library"));
  } catch (exc) {
    reportError(exc, "could not load the library");
  }
}

async function addSource(event) {
  event.preventDefault();
  const ref = $("add-ref").value.trim();
  if (!ref) return;
  const btn = $("add-btn");
  btn.disabled = true;
  try {
    applyLibrary(await api("POST", "/api/sources", {
      ref,
      title: $("add-title").value.trim() || null,
      area: $("add-area").value.trim() || "unfiled",
    }));
    $("add-ref").value = "";
    $("add-title").value = "";
    toast("Added to the queue");
  } catch (exc) {
    reportError(exc, "could not add that source");
  } finally {
    btn.disabled = false;
  }
}

async function removeSource(ref) {
  try {
    applyLibrary(await api("POST", "/api/sources/remove", { ref }));
    toast("Removed from the queue");
  } catch (exc) {
    reportError(exc, "could not remove that source");
  }
}

async function showPreview(ref) {
  openModal("Normalized text", `<div class="field-hint"><span class="spinner"></span> fetching and normalizing…</div>`);
  try {
    const data = await api("POST", "/api/preview", { ref, layout: State.build.layout });
    openModal(
      data.title,
      `<pre class="preview-text">${esc(data.text)}</pre>`,
      `<span class="preview-stats">${data.chars.toLocaleString()} chars · ${data.chunks} chunks · ~${longDuration(data.minutes * 60)} of audio</span>
       <button class="btn btn-sm" data-close>Close</button>`,
    );
  } catch (exc) {
    openModal("Preview failed",
      `<div class="field-error">${esc(exc.message)}</div>${exc.hint ? `<div class="field-hint">${esc(exc.hint)}</div>` : ""}`,
      `<span></span><button class="btn btn-sm" data-close>Close</button>`);
  }
}

async function startBuild(area) {
  try {
    State.live = await api("POST", "/api/build", { area, ...State.build });
    toast(`Building ${area}`, "info");
    renderSidebar();
    renderPanel();
    startPolling();
  } catch (exc) {
    reportError(exc, "could not start the build");
  }
}

async function cancelBuild() {
  if (!State.live) return;
  try {
    await api("POST", `/api/build/${State.live.id}/cancel`);
    toast("Cancelling after the current chapter", "info");
  } catch (exc) {
    reportError(exc, "could not cancel");
  }
}

async function deleteRecording(area) {
  if (!confirm(`Delete the ${area} recording? The queued sources stay.`)) return;
  try {
    await api("DELETE", `/api/recordings/${encodeURIComponent(area)}`);
    toast("Recording deleted");
    await refresh();
  } catch (exc) {
    reportError(exc, "could not delete that recording");
  }
}

// ----------------------------------------------------------------------------
// Build polling — only while a job is live.
// ----------------------------------------------------------------------------
function startPolling() {
  if (State.poll) return;
  State.poll = setInterval(pollBuild, 1500);
}

function stopPolling() {
  clearInterval(State.poll);
  State.poll = null;
}

async function pollBuild() {
  let status;
  try {
    status = await api("GET", "/api/build");
  } catch {
    return; // transient; the next tick retries
  }
  const wasLive = State.live;
  State.live = status.live;

  if (State.live) {
    renderSidebar();
    if (areaByName(State.selected)) renderPanel();
    return;
  }

  stopPolling();
  if (wasLive) {
    const finished = status.recent.find((j) => j.id === wasLive.id);
    if (finished && finished.status === "done") {
      toast(`${finished.area}: ${finished.message}`, "success", 9000);
    } else if (finished) {
      toast(`${finished.area} ${finished.status}: ${finished.message}`, "error", 9000);
    }
  }
  await refresh();
}

// ----------------------------------------------------------------------------
// Boot
// ----------------------------------------------------------------------------
$("add-form").addEventListener("submit", addSource);
$("brand").addEventListener("click", refresh);
$("theme-toggle").addEventListener("click", () =>
  applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light"));

(async function boot() {
  await refresh();
  try {
    const status = await api("GET", "/api/build");
    if (status.live) {
      State.live = status.live;
      renderSidebar();
      renderPanel();
      startPolling();
    }
  } catch { /* the library already loaded; polling can wait */ }
})();
