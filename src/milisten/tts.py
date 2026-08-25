"""Speech synthesis backends. The Kokoro model is loaded lazily and reused."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

SAMPLE_RATE = 24_000

VOICES = {
    "heart": "af_heart",
    "bella": "af_bella",
    "nicole": "af_nicole",
    "michael": "am_michael",
    "fenrir": "am_fenrir",
    "emma": "bf_emma",
    "george": "bm_george",
}


class Synthesizer(Protocol):
    sample_rate: int

    def speak(self, texts: Sequence[str]) -> Iterable[np.ndarray]: ...


@dataclass
class Kokoro:
    voice: str = "af_heart"
    speed: float = 1.0
    lang: str = "a"
    sample_rate: int = SAMPLE_RATE

    def __post_init__(self) -> None:
        try:
            from kokoro import KPipeline
        except ImportError as exc:
            raise RuntimeError(
                "kokoro is not installed — run: uv sync (and brew install espeak-ng)"
            ) from exc
        self._pipeline = KPipeline(lang_code=self.lang)

    def speak(self, texts: Sequence[str]) -> Iterable[np.ndarray]:
        for text in texts:
            audio = [
                chunk.audio.numpy() if hasattr(chunk.audio, "numpy") else np.asarray(chunk.audio)
                for chunk in self._pipeline(text, voice=self.voice, speed=self.speed)
            ]
            yield np.concatenate(audio) if audio else np.zeros(1, dtype=np.float32)


@dataclass
class MacSay:
    """Fallback that needs nothing installed. Useful for pipeline smoke tests."""

    voice: str = "Samantha"
    rate: int = 190
    sample_rate: int = 22_050

    def speak(self, texts: Sequence[str]) -> Iterable[np.ndarray]:
        import subprocess
        import tempfile

        import soundfile as sf

        for text in texts:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "s.aiff"
                subprocess.run(
                    ["say", "-v", self.voice, "-r", str(self.rate), "-o", str(out), text],
                    check=True,
                )
                data, rate = sf.read(out, dtype="float32", always_2d=False)
            self.sample_rate = rate
            yield data if data.ndim == 1 else data.mean(axis=1)


def build(engine: str, voice: str, speed: float) -> Synthesizer:
    if engine == "say":
        return MacSay(voice=voice if voice[0].isupper() else "Samantha")
    return Kokoro(voice=VOICES.get(voice, voice), speed=speed)


def render(synth: Synthesizer, texts: Sequence[str], dest: Path) -> float:
    import soundfile as sf

    silence = np.zeros(int(synth.sample_rate * 0.35), dtype=np.float32)
    pieces: list[np.ndarray] = []
    for audio in synth.speak(texts):
        pieces.extend((audio.astype(np.float32), silence))
    track = np.concatenate(pieces) if pieces else silence
    sf.write(dest, track, synth.sample_rate)
    return len(track) / synth.sample_rate
