/* Kokoro synthesis, off the main thread.
 *
 * On the main thread the wasm backend blocks for seconds per chunk and the tab
 * stops repainting mid-sentence, so all model loading and generation happens here
 * and only finished WAV bytes cross back. */

const KOKORO = "https://cdn.jsdelivr.net/npm/kokoro-js@1.2.1/+esm";

let tts = null;

async function load(model) {
  const { KokoroTTS } = await import(KOKORO);
  tts = await KokoroTTS.from_pretrained(model, {
    dtype: "q8",
    device: "wasm",
    progress_callback: (p) => {
      if (p?.status === "progress" && p.total) {
        self.postMessage({ type: "progress", pct: Math.round((p.loaded / p.total) * 100) });
      }
    },
  });
  self.postMessage({ type: "ready", voices: Object.keys(tts.voices || {}) });
}

async function generate(id, text, voice, speed) {
  if (!tts) throw new Error("voice is not loaded");
  const audio = await tts.generate(text, { voice: voice || "af_heart", speed: speed || 1 });
  const wav = await audio.toBlob().arrayBuffer();
  // Transfer rather than copy: these are megabytes per chunk.
  self.postMessage({ type: "audio", id, wav }, [wav]);
}

self.onmessage = async (event) => {
  const message = event.data;
  try {
    if (message.type === "load") await load(message.model);
    else if (message.type === "generate") {
      await generate(message.id, message.text, message.voice, message.speed);
    }
  } catch (err) {
    self.postMessage({ type: "error", id: message.id, message: String(err?.message || err) });
  }
};
