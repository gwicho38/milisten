"use strict";
/* milisten on GitHub Pages.
 *
 * The rewriting is not re-implemented here: Pyodide runs the real
 * src/milisten/{models,normalize,chunk}.py, staged verbatim at deploy time, so this
 * page and the CLI cannot drift. The voice is the same Kokoro-82M the CLI uses,
 * via ONNX in this tab.
 *
 * Playback goes through Web Audio rather than an <audio> element: decodeAudioData
 * works in contexts where HTMLMediaElement quietly refuses to initialise, and it
 * gives per-chunk scheduling for free. */

const PYODIDE_MODULES = ["__init__.py", "models.py", "normalize.py", "chunk.py"];
// Pinned. pdf.js v4 and kokoro-js are ESM-only, so these are dynamic imports and
// cannot carry Subresource Integrity; the CSP limits them to this one origin.
const PDFJS = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.min.mjs";
const PDFJS_WORKER = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.worker.min.mjs";
const KOKORO = "https://cdn.jsdelivr.net/npm/kokoro-js@1.2.1/+esm";
const KOKORO_MODEL = "onnx-community/Kokoro-82M-v1.0-ONNX";
// A browser cannot read another origin. Links go through this extractor; files and
// typed text never leave the tab. The page says so plainly.
const READER = "https://r.jina.ai/";
const LEVELS = { 1: "light", 2: "standard", 3: "full" };
const LEVEL_HINTS = {
  1: "numbers, references and links — best with this voice",
  2: "also expands dates and abbreviations",
  3: "also spells out acronyms — for robotic voices",
};

const $ = (id) => document.getElementById(id);
const S = {
  py: null,
  tts: null,
  ttsLoading: null,
  raw: "",
  normalized: "",
  chunks: [],
  changes: [],
  view: "normalized",
  ctx: null,
  source: null,
  playing: false,
  index: 0,
  wavs: [],
};

// ---------------------------------------------------------------------------
// Chrome
// ---------------------------------------------------------------------------
function toast(message, kind = "info", ms = 6000) {
  const node = document.createElement("div");
  node.className = `toast toast-${kind}`;
  node.textContent = message;
  $("toast-stack").append(node);
  setTimeout(() => node.remove(), ms);
}

function status(text, spinning = false) {
  const el = $("status");
  el.hidden = !text;
  el.replaceChildren();
  if (!text) return;
  if (spinning) {
    const s = document.createElement("span");
    s.className = "spinner";
    el.append(s, document.createTextNode(" "));
  }
  el.append(document.createTextNode(text));
}

const THEME_KEY = "milisten.theme";
function applyTheme(t) {
  if (t === "light") document.documentElement.setAttribute("data-theme", "light");
  else document.documentElement.removeAttribute("data-theme");
  try { localStorage.setItem(THEME_KEY, t); } catch { /* private mode */ }
}
try { applyTheme(localStorage.getItem(THEME_KEY) || "dark"); } catch { applyTheme("dark"); }
$("theme-toggle").addEventListener("click", () =>
  applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light"));

// ---------------------------------------------------------------------------
// Pyodide — the real normalizer
// ---------------------------------------------------------------------------
async function bootPython() {
  const py = await loadPyodide();
  const sources = await Promise.all(PYODIDE_MODULES.map((name) =>
    fetch(`./milisten/${name}`).then((r) => {
      if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
      return r.text();
    })));
  py.FS.mkdirTree("/home/pyodide/milisten");
  PYODIDE_MODULES.forEach((n, i) => py.FS.writeFile(`/home/pyodide/milisten/${n}`, sources[i]));
  py.runPython(`
import sys
sys.path.insert(0, "/home/pyodide")
from milisten.normalize import normalize
from milisten.chunk import chunk

def run(text, level):
    out = normalize(text, level)
    return out, [c.text for c in chunk(out)]

def per_line(text, level):
    pairs = []
    for line in text.split("\\n"):
        if not line.strip():
            continue
        after = normalize(line, level)
        if after and after != line.strip():
            pairs.append((line.strip(), after))
    return pairs
`);
  S.py = py;
  $("runtime").textContent = "ready · nothing typed leaves this tab";
  return py;
}

// ---------------------------------------------------------------------------
// Input: link, file, or text — one box
// ---------------------------------------------------------------------------
const looksLikeUrl = (v) => /^(https?:\/\/|www\.)\S+$/i.test(v.trim());

async function fromUrl(url) {
  const target = /^www\./i.test(url) ? `https://${url}` : url;
  status(`fetching ${new URL(target).hostname}…`, true);
  try {
    const direct = await fetch(target, { mode: "cors" });
    if (direct.ok) {
      const type = direct.headers.get("content-type") || "";
      if (type.includes("pdf")) {
        return await pdfToText(new Blob([await direct.arrayBuffer()]));
      }
      const html = await direct.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      doc.querySelectorAll("script,style,nav,header,footer,aside").forEach((n) => n.remove());
      const text = (doc.body?.innerText || doc.body?.textContent || "").trim();
      if (text.length > 400) return text;
    }
  } catch { /* expected: almost no publisher allows cross-origin reads */ }

  status("that site blocks browsers — extracting via r.jina.ai…", true);
  const relayed = await fetch(READER + target);
  if (!relayed.ok) {
    throw new Error(
      `could not read that link (HTTP ${relayed.status}). Download the page or PDF and drop it in.`);
  }
  const text = (await relayed.text()).trim();
  if (text.length < 400) throw new Error("that link yielded almost no text — try downloading it");
  return stripRelayHeader(text);
}

/** The extractor prefixes a metadata block. Left in, the voice reads out
 *  "URL Source colon…" and an ISO timestamp before reaching the article. */
function stripRelayHeader(text) {
  const marker = text.indexOf("Markdown Content:");
  if (marker === -1) return text;
  const title = /^Title:\s*(.+)$/m.exec(text.slice(0, marker));
  const body = text
    .slice(marker + "Markdown Content:".length)
    // The extractor leaves degraded image placeholders behind, e.g. "!Image 3".
    .replace(/^!?\[?Image \d+\]?.*$/gm, "")
    .trim();
  return title ? `${title[1].trim()}\n\n${body}` : body;
}

async function pdfToText(file) {
  const pdfjs = await import(PDFJS);
  pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
  const doc = await pdfjs.getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
  const pages = [];
  for (let n = 1; n <= doc.numPages; n += 1) {
    status(`reading page ${n} of ${doc.numPages}…`, true);
    const content = await (await doc.getPage(n)).getTextContent();
    const lines = [];
    let line = "";
    let lastY = null;
    for (const item of content.items) {
      const y = Math.round(item.transform[5]);
      if (lastY !== null && Math.abs(y - lastY) > 2) { lines.push(line.trim()); line = ""; }
      line += item.str;
      lastY = y;
    }
    lines.push(line.trim());
    pages.push(lines.filter(Boolean).join("\n"));
  }
  return pages.join("\n\n");
}

async function resolveInput() {
  const value = $("omni").value.trim();
  if (!value) throw new Error("paste a link or some text, or drop a file");
  if (looksLikeUrl(value)) return fromUrl(value);
  if (value.length < 40) throw new Error("that is too short to read — paste more text or a link");
  return value;
}

async function ingestFile(file) {
  status(`reading ${file.name}…`, true);
  const text = /\.pdf$/i.test(file.name) ? await pdfToText(file) : await file.text();
  if (!text.trim()) throw new Error("no extractable text — it may be a scanned image");
  $("omni").value = `${file.name} · ${text.length.toLocaleString()} chars`;
  $("omni").dataset.loaded = "file";
  if (/\.pdf$/i.test(file.name)) {
    toast("PDF reading order can differ from the CLI's pdftotext — check the text panel", "info", 8000);
  }
  return text;
}

// ---------------------------------------------------------------------------
// Normalize
// ---------------------------------------------------------------------------
function level() { return Number($("level-input").value); }

function renderText() {
  const out = $("out");
  if (S.view === "normalized") { out.textContent = S.normalized; return; }
  if (!S.changes.length) { out.textContent = "Nothing needed rewriting."; return; }
  out.replaceChildren(...S.changes.flatMap(([before, after]) => {
    const b = document.createElement("div"); b.className = "diff-before"; b.textContent = before;
    const a = document.createElement("div"); a.className = "diff-after"; a.textContent = after;
    const g = document.createElement("div"); g.className = "diff-gap";
    return [b, a, g];
  }));
}

function renderChunks() {
  $("chunks").replaceChildren(...S.chunks.map((text, i) => {
    const row = document.createElement("button");
    row.className = "chunk-row";
    row.setAttribute("aria-current", String(i === S.index && S.playing));
    const n = document.createElement("span"); n.className = "chunk-idx"; n.textContent = String(i + 1);
    const t = document.createElement("span"); t.className = "chunk-text"; t.textContent = text;
    row.append(n, t);
    row.addEventListener("click", () => play(i));
    return row;
  }));
}

function normalizeNow() {
  if (!S.py || !S.raw) return;
  const run = S.py.globals.get("run");
  const perLine = S.py.globals.get("per_line");
  const lvl = level();
  const res = run(S.raw, lvl);
  S.normalized = res.get(0);
  S.chunks = res.get(1).toJs();
  res.destroy();
  const pairs = perLine(S.raw, lvl);
  S.changes = pairs.toJs().map((p) => [p[0], p[1]]);
  pairs.destroy();
  S.wavs = [];

  const secs = S.normalized.length / 27;
  $("out-stats").textContent =
    `· ${S.normalized.length.toLocaleString()} chars, ${S.chunks.length} chunks, ` +
    `~${secs < 60 ? "<1" : Math.round(secs / 60)} min`;
  $("text-details").hidden = false;
  $("player").hidden = false;
  renderText();
  renderChunks();
}

// ---------------------------------------------------------------------------
// Voice
// ---------------------------------------------------------------------------
async function loadKokoro() {
  if (S.tts) return S.tts;
  if (S.ttsLoading) return S.ttsLoading;
  S.ttsLoading = (async () => {
    status("loading the Kokoro voice (~86 MB, once)…", true);
    // Synthesis runs in a worker. On the main thread the wasm backend locks the tab
    // solid for seconds per chunk — the UI stops repainting mid-sentence.
    const worker = new Worker(new URL("./tts-worker.js", import.meta.url), { type: "module" });
    const names = await new Promise((resolve, reject) => {
      worker.onmessage = (e) => {
        const m = e.data;
        if (m.type === "progress") status(`downloading the voice — ${m.pct}%`, true);
        else if (m.type === "ready") resolve(m.voices);
        else if (m.type === "error") reject(new Error(m.message));
      };
      worker.onerror = (e) => reject(new Error(e.message || "worker failed"));
      worker.postMessage({ type: "load", model: KOKORO_MODEL });
    });

    let seq = 0;
    const pending = new Map();
    worker.onmessage = (e) => {
      const m = e.data;
      if (m.type === "progress") return;
      const entry = pending.get(m.id);
      if (!entry) return;
      pending.delete(m.id);
      if (m.type === "audio") entry.resolve(m.wav);
      else entry.reject(new Error(m.message || "synthesis failed"));
    };
    S.tts = {
      voices: names,
      generate: (text, voice, speed) => new Promise((resolve, reject) => {
        const id = (seq += 1);
        pending.set(id, { resolve, reject });
        worker.postMessage({ type: "generate", id, text, voice, speed });
      }),
    };
    if (names.length) {
      const select = $("voice-select");
      const keep = select.value;
      select.replaceChildren(...names.map((n) => {
        const o = document.createElement("option");
        o.value = n;
        o.textContent = n.replace(/^([abe])([fm])_/, (_, l, g) =>
          `${g === "f" ? "♀" : "♂"} ${l === "a" ? "US" : l === "b" ? "UK" : "EU"} `);
        return o;
      }));
      select.value = names.includes(keep) ? keep : (names.includes("af_heart") ? "af_heart" : names[0]);
    }
    $("runtime").textContent = "Kokoro · in-browser";
    return tts;
  })();
  try { return await S.ttsLoading; } finally { S.ttsLoading = null; }
}

async function synthesize(i) {
  if (S.wavs[i]) return S.wavs[i];
  const wav = await S.tts.generate(
    S.chunks[i],
    $("voice-select").value || "af_heart",
    Number($("rate-input").value),
  );
  // decodeAudioData detaches the buffer it is given, so keep a copy for download.
  const forDownload = wav.slice(0);
  const buffer = await S.ctx.decodeAudioData(wav);
  S.wavs[i] = { buffer, blob: new Blob([forDownload], { type: "audio/wav" }) };
  return S.wavs[i];
}

function stop() {
  S.playing = false;
  if (S.source) { try { S.source.onended = null; S.source.stop(); } catch { /* already stopped */ } }
  S.source = null;
  $("play-label").textContent = "▶";
  renderChunks();
}

async function play(from = 0) {
  if (!S.chunks.length) return;
  stop();
  S.ctx = S.ctx || new AudioContext();
  await S.ctx.resume();

  try {
    await loadKokoro();
  } catch (err) {
    status("");
    toast(`voice failed to load: ${err.message}`, "error", 10000);
    return;
  }

  S.playing = true;
  $("play-label").textContent = "❚❚";

  for (let i = from; i < S.chunks.length && S.playing; i += 1) {
    S.index = i;
    renderChunks();
    $("progress").style.width = `${((i / S.chunks.length) * 100).toFixed(1)}%`;
    status(`speaking ${i + 1} of ${S.chunks.length}`, false);

    let current;
    try {
      current = await synthesize(i);
    } catch (err) {
      toast(`chunk ${i + 1} failed: ${err.message}`, "error");
      break;
    }
    if (!S.playing) break;

    // Start the next chunk generating while this one plays.
    const ahead = i + 1 < S.chunks.length ? synthesize(i + 1).catch(() => null) : null;

    await new Promise((resolve) => {
      const src = S.ctx.createBufferSource();
      src.buffer = current.buffer;
      src.connect(S.ctx.destination);
      src.onended = resolve;
      S.source = src;
      src.start();
    });
    await ahead;
  }

  if (S.playing) {
    $("progress").style.width = "100%";
    status(`done · ${S.chunks.length} chunks`);
    $("download-btn").hidden = false;
  }
  stop();
}

function downloadWav() {
  const ready = S.wavs.filter(Boolean);
  if (!ready.length) { toast("nothing rendered yet — press play first", "info"); return; }
  const url = URL.createObjectURL(ready[0].blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "milisten.wav";
  a.click();
  URL.revokeObjectURL(url);
  if (ready.length < S.chunks.length) {
    toast("only the chunks rendered so far are in that file", "info");
  }
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------
$("omni-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (S.playing) { stop(); status(""); return; }
  if (S.chunks.length && $("omni").dataset.settled === S.raw.slice(0, 64)) { play(0); return; }
  const btn = $("play-btn");
  btn.disabled = true;
  try {
    S.raw = await resolveInput();
    $("omni").dataset.settled = S.raw.slice(0, 64);
    normalizeNow();
    status("");
    await play(0);
  } catch (err) {
    status("");
    toast(err.message, "error", 9000);
  } finally {
    btn.disabled = false;
  }
});

$("attach-btn").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    S.raw = await ingestFile(file);
    $("omni").dataset.settled = S.raw.slice(0, 64);
    normalizeNow();
    status("ready — press play");
  } catch (err) {
    status("");
    toast(err.message, "error", 9000);
  }
});

$("stop-btn").addEventListener("click", () => { stop(); status(""); $("progress").style.width = "0%"; });
$("download-btn").addEventListener("click", downloadWav);

$("rate-input").addEventListener("input", () => {
  $("rate-out").textContent = `${Number($("rate-input").value).toFixed(2)}×`;
  S.wavs = [];
});
$("level-input").addEventListener("input", () => {
  const lvl = level();
  $("level-out").textContent = LEVELS[lvl];
  $("level-hint").textContent = LEVEL_HINTS[lvl];
  if (S.raw) normalizeNow();
});
$("voice-select").addEventListener("change", () => { S.wavs = []; });

$("tab-normalized").addEventListener("click", () => {
  S.view = "normalized";
  $("tab-normalized").setAttribute("aria-pressed", "true");
  $("tab-diff").setAttribute("aria-pressed", "false");
  renderText();
});
$("tab-diff").addEventListener("click", () => {
  S.view = "diff";
  $("tab-diff").setAttribute("aria-pressed", "true");
  $("tab-normalized").setAttribute("aria-pressed", "false");
  renderText();
});
$("copy-btn").addEventListener("click", async () => {
  await navigator.clipboard.writeText(S.normalized);
  toast("copied");
});

let dragDepth = 0;
window.addEventListener("dragenter", (e) => {
  e.preventDefault(); dragDepth += 1; $("drop-veil").hidden = false;
});
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (!dragDepth) $("drop-veil").hidden = true;
});
window.addEventListener("drop", async (e) => {
  e.preventDefault();
  dragDepth = 0;
  $("drop-veil").hidden = true;

  const dt = e.dataTransfer;
  const file = dt?.files?.[0];
  // A link or selection dragged from another tab arrives as text, not a file. Reading
  // only dt.files silently ignored it while the overlay promised otherwise.
  const dropped = (dt?.getData("text/uri-list") || dt?.getData("text/plain") || "").trim();
  const firstUrl = dropped.split(/\s+/).find(looksLikeUrl);

  try {
    if (file) {
      S.raw = await ingestFile(file);
    } else if (firstUrl) {
      $("omni").value = firstUrl;
      S.raw = await fromUrl(firstUrl);
    } else if (dropped.length >= 40) {
      $("omni").value = `dropped text · ${dropped.length.toLocaleString()} chars`;
      S.raw = dropped;
    } else {
      toast("drop a file, a link, or a decent chunk of text", "info");
      return;
    }
    $("omni").dataset.settled = S.raw.slice(0, 64);
    normalizeNow();
    status("ready — press play");
  } catch (err) {
    status("");
    toast(err.message, "error", 9000);
  }
});

$("level-out").textContent = LEVELS[level()];
$("level-hint").textContent = LEVEL_HINTS[level()];
$("rate-out").textContent = "1.00×";

bootPython().catch((err) => {
  $("runtime").textContent = "failed to start";
  toast(`Python failed to load: ${err.message}`, "error", 12000);
});
