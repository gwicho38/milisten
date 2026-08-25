import numpy as np
import soundfile as sf

from milisten.tts import VOICES, render


class FakeSynth:
    sample_rate = 24_000

    def speak(self, texts):
        for index, _ in enumerate(texts):
            yield np.full(self.sample_rate, 0.1 * (index + 1), dtype=np.float32)


def test_reported_duration_matches_the_written_file(tmp_path):
    out = tmp_path / "a.wav"
    seconds = render(FakeSynth(), ["one", "two", "three"], out)
    data, rate = sf.read(out)
    assert seconds == len(data) / rate


def test_gap_is_inserted_between_chunks(tmp_path):
    out = tmp_path / "a.wav"
    seconds = render(FakeSynth(), ["one", "two"], out)
    assert seconds > 2.0


def test_empty_input_still_produces_a_readable_file(tmp_path):
    out = tmp_path / "empty.wav"
    assert render(FakeSynth(), [], out) > 0
    assert sf.read(out)[0].size > 0


def test_output_is_16_bit_mono(tmp_path):
    out = tmp_path / "a.wav"
    render(FakeSynth(), ["one"], out)
    info = sf.info(out)
    assert info.subtype == "PCM_16"
    assert info.channels == 1


def test_named_voices_map_to_kokoro_identifiers():
    assert VOICES["heart"] == "af_heart"
    assert all(v[0] in "abe" and "_" in v for v in VOICES.values())
