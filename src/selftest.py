"""Headless verification: imports, model load, and a transcription pass."""
import av_shim  # noqa: F401  -- must precede faster_whisper import
import time
import numpy as np
from faster_whisper import WhisperModel

import main  # exercises all imports + config load

cfg = main.load_config()
print("config loaded:", cfg["model_size"], cfg["hotkey"])

fg = main.foreground_process_name()
print("foreground proc detect:", fg or "(none)")

print("loading model...")
t0 = time.time()
model = WhisperModel(cfg["model_size"], device=cfg["device"], compute_type=cfg["compute_type"])
print(f"model loaded in {time.time()-t0:.1f}s")

# 2s of silence -> should transcribe to empty/near-empty without error.
audio = np.zeros(cfg["sample_rate"] * 2, dtype=np.float32)
t0 = time.time()
segments, _ = model.transcribe(audio, language="en", beam_size=1)
text = "".join(s.text for s in segments).strip()
print(f"transcribe ran in {time.time()-t0:.1f}s, output={text!r}")
print("SELFTEST OK")
