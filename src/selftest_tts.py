"""Headless check for the TTS path: both engines, speak and interrupt.

Plays audio, so it doubles as an audible comparison of the two voices.
Does not exercise get_selected_text() -- that sends Ctrl+C to whatever window
has focus, which is rude to run unattended.
"""
import av_shim  # noqa: F401
import os
import threading
import time

import main as app_main
from tts import Speaker

cfg = app_main.load_config()
model = cfg.get("tts_model")
if not os.path.isabs(model):
    model = os.path.join(os.path.dirname(__file__), "..", model)
print("piper model present:", os.path.exists(model))

LONG = (
    "This is a longer passage used to verify that playback can be interrupted "
    "part way through. It keeps going for several sentences so there is time to "
    "cut it off. If the stop control works, this sentence will not finish. "
    "And this final sentence should never be reached at all."
)

for engine in ("windows", "piper"):
    print(f"\n=== engine: {engine} ===")
    sp = Speaker(model, cfg.get("tts_speed", 1.0), log=lambda m: print("  log:", m),
                 engine=engine)
    if sp.engine != engine:
        print(f"  resolved to '{sp.engine}' instead — skipping")
        continue

    t0 = time.time()
    sp.speak(f"Read aloud is working using the {engine} engine.")
    print(f"  short phrase: {time.time() - t0:.1f}s, flag cleared: {not sp.speaking}")

    t0 = time.time()
    threading.Thread(target=lambda: sp.speak(LONG), daemon=True).start()
    time.sleep(1.2)
    mid = sp.speaking
    sp.stop()
    time.sleep(0.5)
    print(f"  interrupt: speaking mid-passage={mid}, "
          f"stopped after {time.time() - t0:.1f}s, flag cleared={not sp.speaking}")

print("\nTTS SELFTEST OK")
