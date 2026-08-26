"use strict";
/* milisten on GitHub Pages — no server, no backend, nothing leaves the tab.
 *
 * The normalizer is not re-implemented here. Pyodide runs the real
 * src/milisten/{models,normalize,chunk}.py, copied in verbatim at deploy time, so
 * this page and the CLI cannot drift apart. */

const PY_MODULES = ["__init__.py", "models.py", "normalize.py", "chunk.py"];
// pdf.js v4 is ESM-only, so this has to be a dynamic import, which cannot carry
// Subresource Integrity. The version is pinned and the CSP allows this one origin.
const PDFJS = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.min.mjs";
const PDFJS_WORKER = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/pdf.worker.min.mjs";
const CHARS_PER_SECOND = 27;
const DRAFT_KEY = "milisten.draft";
const THEME_KEY = "milisten.theme";

const $ = (id) => document.getElementById(id);
const State = {
  py: null,
  raw: "",
  normalized: "",
  chunks: [],
  changes: [],
  view: "normalized",
  speaking: false,
  index: 0,
};

// ---------------------------------------------------------------------------
// Chrome
// ---------------------------------------------------------------------------
function toast(message, kind = "info", ms = 5000) {
  const node = document.createElement("div");
  node.className = `toast toast-${kind}`;
  node.textContent = message;
  $("toast-stack").append(node);
  setTimeout(() => node.remove(), ms);
}

function applyTheme(theme) {
  if (theme === "light") document.documentElement.setAttribute("data-theme", "light");
  else document.documentElement.removeAttribute("data-theme");
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* private mode */ }
}
try { applyTheme(localStorage.getItem(THEME_KEY) || "dark"); } catch { applyTheme("dark"); }
$("theme-toggle").addEventListener("click", () =>
  applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light"));

function minutes(chars) {
  const mins = chars / CHARS_PER_SECOND / 60;
  return mins < 1 ? "<1 min" : `${Math.round(mins)} min`;
}

// ---------------------------------------------------------------------------
// Pyodide: load the real modules rather than a port of them
// ---------------------------------------------------------------------------
async function bootPython() {
  const runtime = $("runtime");
  runtime.textContent = "loading Python…";
  const py = await loadPyodide();

  const sources = await Promise.all(
    PY_MODULES.map((name) =>
      fetch(`./milisten/${name}`).then((r) => {
        if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
        return r.text();
      })),
  );

  py.FS.mkdirTree("/home/pyodide/milisten");
  PY_MODULES.forEach((name, i) =>
    py.FS.writeFile(`/home/pyodide/milisten/${name}`, sources[i]));

  py.runPython(`
import sys
sys.path.insert(0, "/home/pyodide")
from milisten.normalize import normalize
from milisten.chunk import chunk

def run(text):
    out = normalize(text)
    return out, [c.text for c in chunk(out)]

def per_line(text):
    pairs = []
    for line in text.split("\\n"):
        if not line.strip():
            continue
        after = normalize(line)
        if after and after != line.strip():
            pairs.append((line.strip(), after))
    return pairs
`);

  State.py = py;
  runtime.textContent = `python ${py.version.split(" ")[0]} · in-browser`;
  $("normalize-btn").disabled = !$("raw").value.trim();
  return py;
}

// ---------------------------------------------------------------------------
// Input
// ---------------------------------------------------------------------------
async function pdfToText(file) {
  const pdfjs = await import(PDFJS);
  pdfjs.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
  const data = new Uint8Array(await file.arrayBuffer());
  const doc = await pdfjs.getDocument({ data }).promise;
  const pages = [];
  for (let n = 1; n <= doc.numPages; n += 1) {
    const page = await doc.getPage(n);
    const content = await page.getTextContent();
    let line = "";
    let lastY = null;
    const lines = [];
    for (const item of content.items) {
      const y = Math.round(item.transform[5]);
      if (lastY !== null && Math.abs(y - lastY) > 2) {
        lines.push(line.trim());
        line = "";
      }
      line += item.str;
      lastY = y;
    }
    lines.push(line.trim());
    pages.push(lines.filter(Boolean).join("\n"));
    $("file-note").textContent = `reading page ${n} of ${doc.numPages}…`;
  }
  return pages.join("\n\n");
}

async function ingest(file) {
  const note = $("file-note");
  note.textContent = `reading ${file.name}…`;
  try {
    const text = /\.pdf$/i.test(file.name) ? await pdfToText(file) : await file.text();
    if (!text.trim()) throw new Error("no extractable text — it may be a scanned image");
    $("raw").value = text;
    onRawChanged();
    note.textContent = `${file.name} · ${text.length.toLocaleString()} chars`;
    if (/\.pdf$/i.test(file.name)) {
      toast("PDF reading order can differ from the CLI's pdftotext — check the output", "info", 8000);
    }
  } catch (err) {
    note.textContent = "";
    toast(`${file.name}: ${err.message}`, "error", 8000);
  }
}

function onRawChanged() {
  const raw = $("raw").value;
  State.raw = raw;
  $("raw-stats").textContent = raw.trim()
    ? `${raw.length.toLocaleString()} chars in`
    : "";
  $("normalize-btn").disabled = !raw.trim() || !State.py;
  try { localStorage.setItem(DRAFT_KEY, raw); } catch { /* private mode */ }
}

// ---------------------------------------------------------------------------
// Normalize
// ---------------------------------------------------------------------------
function renderOutput() {
  const out = $("out");
  if (State.view === "normalized") {
    out.textContent = State.normalized;
    return;
  }
  if (!State.changes.length) {
    out.textContent = "No line changed. Nothing here needed rewriting for speech.";
    return;
  }
  out.replaceChildren(...State.changes.flatMap(([before, after]) => {
    const b = document.createElement("div");
    b.className = "diff-before";
    b.textContent = before;
    const a = document.createElement("div");
    a.className = "diff-after";
    a.textContent = after;
    const gap = document.createElement("div");
    gap.className = "diff-gap";
    return [b, a, gap];
  }));
}

function renderChunks() {
  const list = $("chunks");
  list.replaceChildren(...State.chunks.map((text, i) => {
    const row = document.createElement("button");
    row.className = "chunk-row";
    row.dataset.idx = String(i);
    row.setAttribute("aria-current", String(i === State.index && State.speaking));
    const n = document.createElement("span");
    n.className = "chunk-idx";
    n.textContent = String(i + 1);
    const body = document.createElement("span");
    body.className = "chunk-text";
    body.textContent = text;
    row.append(n, body);
    row.addEventListener("click", () => speakFrom(i));
    return row;
  }));
}

async function doNormalize() {
  if (!State.py) return;
  const btn = $("normalize-btn");
  btn.disabled = true;
  btn.textContent = "Normalizing…";
  try {
    const run = State.py.globals.get("run");
    const perLine = State.py.globals.get("per_line");
    const result = run(State.raw);
    State.normalized = result.get(0);
    State.chunks = result.get(1).toJs();
    result.destroy();
    const pairs = perLine(State.raw);
    State.changes = pairs.toJs().map((p) => [p[0], p[1]]);
    pairs.destroy();

    $("out-stats").textContent =
      `${State.normalized.length.toLocaleString()} chars · ${State.chunks.length} chunks · ` +
      `~${minutes(State.normalized.length)} of speech · ${State.changes.length} lines rewritten`;
    $("output-card").hidden = false;
    $("speak-card").hidden = false;
    renderOutput();
    renderChunks();
    $("output-card").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    toast(`normalize failed: ${err.message}`, "error", 9000);
  } finally {
    btn.textContent = "Normalize";
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Speech
// ---------------------------------------------------------------------------
function loadVoices() {
  const select = $("voice-select");
  const voices = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("en"));
  if (!voices.length) return;
  select.replaceChildren(...voices.map((v, i) => {
    const opt = document.createElement("option");
    opt.value = String(i);
    opt.textContent = `${v.name} (${v.lang})`;
    return opt;
  }));
  select._voices = voices;
  const preferred = voices.findIndex((v) => v.localService);
  select.value = String(preferred >= 0 ? preferred : 0);
}

function setControls(active) {
  State.speaking = active;
  $("play-btn").disabled = active;
  $("pause-btn").disabled = !active;
  $("stop-btn").disabled = !active;
}

function speakFrom(start) {
  speechSynthesis.cancel();
  const select = $("voice-select");
  const voice = (select._voices || [])[Number(select.value)] || null;
  const rate = Number($("rate-input").value);
  setControls(true);

  const next = (i) => {
    if (i >= State.chunks.length) {
      setControls(false);
      $("progress").style.width = "100%";
      renderChunks();
      return;
    }
    State.index = i;
    renderChunks();
    $("progress").style.width = `${((i / State.chunks.length) * 100).toFixed(1)}%`;
    const utter = new SpeechSynthesisUtterance(State.chunks[i]);
    if (voice) utter.voice = voice;
    utter.rate = rate;
    utter.onend = () => { if (State.speaking) next(i + 1); };
    utter.onerror = (e) => {
      if (e.error !== "interrupted" && e.error !== "canceled") {
        toast(`speech error: ${e.error}`, "error");
        setControls(false);
      }
    };
    speechSynthesis.speak(utter);
  };
  next(start);
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------
$("raw").addEventListener("input", onRawChanged);
$("normalize-btn").addEventListener("click", doNormalize);
$("browse-btn").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", (e) => {
  if (e.target.files[0]) ingest(e.target.files[0]);
});
$("clear-btn").addEventListener("click", () => {
  $("raw").value = "";
  $("file-note").textContent = "";
  $("output-card").hidden = true;
  $("speak-card").hidden = true;
  speechSynthesis.cancel();
  setControls(false);
  onRawChanged();
});
$("sample-btn").addEventListener("click", () => {
  $("raw").value = SAMPLE;
  onRawChanged();
  doNormalize();
});
$("copy-btn").addEventListener("click", async () => {
  await navigator.clipboard.writeText(State.normalized);
  toast("Normalized text copied");
});
$("tab-normalized").addEventListener("click", () => {
  State.view = "normalized";
  $("tab-normalized").setAttribute("aria-pressed", "true");
  $("tab-diff").setAttribute("aria-pressed", "false");
  renderOutput();
});
$("tab-diff").addEventListener("click", () => {
  State.view = "diff";
  $("tab-diff").setAttribute("aria-pressed", "true");
  $("tab-normalized").setAttribute("aria-pressed", "false");
  renderOutput();
});
$("play-btn").addEventListener("click", () => speakFrom(0));
$("pause-btn").addEventListener("click", () => {
  if (speechSynthesis.paused) { speechSynthesis.resume(); $("pause-btn").textContent = "Pause"; }
  else { speechSynthesis.pause(); $("pause-btn").textContent = "Resume"; }
});
$("stop-btn").addEventListener("click", () => {
  speechSynthesis.cancel();
  setControls(false);
  $("progress").style.width = "0%";
  renderChunks();
});

const drop = $("drop");
["dragenter", "dragover"].forEach((evt) =>
  drop.addEventListener(evt, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((evt) =>
  drop.addEventListener(evt, () => drop.classList.remove("over")));
drop.addEventListener("drop", (e) => {
  e.preventDefault();
  if (e.dataTransfer.files[0]) ingest(e.dataTransfer.files[0]);
});

speechSynthesis.addEventListener("voiceschanged", loadVoices);
loadVoices();
if (!("speechSynthesis" in window)) {
  $("speak-note").textContent = "this browser has no speech synthesis";
}

try {
  const draft = localStorage.getItem(DRAFT_KEY);
  if (draft) $("raw").value = draft;
} catch { /* private mode */ }
onRawChanged();

const SAMPLE = `SEC, Semiannual Reporting, Release Nos. 33-11414, File No. S7-2026-15,
91 Fed. Reg. 24968 (7 May 2026), 91pp. Comments closed 6 July 2026.
See https://www.sec.gov/rules-regulations/2026/05/s7-2026-15 for the docket.

In Rutledge v. Clearway Energy (Del. 27 Feb. 2026) the court upheld SB 21.
Purl v. HHS, No. 2:24-cv-00228-Z (N.D. Tex. 18 June 2025) vacated most of the
2024 reproductive health privacy rule, though the NPRM under RIN 0945-AA22 is
still pending before OMB.

Reg. (EU) 2026/1744 entered into force 27 July 2026. Annex III high-risk duties
are deferred to 2 Dec. 2027; Art. 50(2) watermarking applies from 2 Dec. 2026.
Per the EDPB and EDPS, e.g. Joint Opinion 2/2026, the GDPR changes remain
contested. Earnouts moved 26%->18% across 2,300+ deals worth $569bn, 2020-2025.`;

bootPython().catch((err) => {
  $("runtime").textContent = "python failed to load";
  toast(`Pyodide failed: ${err.message}`, "error", 12000);
});
